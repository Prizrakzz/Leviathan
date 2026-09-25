"""FIX ROUND 2 (09-24 re-smoke), lane V -- the verifier's half of CONTRACT K1 / K4 / K7 and item 28f.

Every prose fixture below is VERBATIM from the 09-24 raw drafts (resmoke_0924/answers/*.trace.json
`raw_draft.preverify_*`) and every row is that turn's served row (`served_rows`, the [N] index kept), unless
the pin says it is a synthetic shape (the [E] evidence menu is not persisted in any trace, so the ledger
pins rebuild it from the documents the 09-23 / 09-24 traces DID resolve: `citation_resolved`).

  K1  address-first [E] resolution -- `verify_citations(..., evidence_chunks=...)`; absent kwarg = HEAD
  K4  `bind_figures` (pure) + `unit_family` + the `unit_mismatch` report key (counted, never charged)
  K7  the card's display scale is a member of a STAMPED call's rows and unit class (typed)
  28f a card-declared definition phrase is masked like a unit phrase on a stamped call of that metric
"""
from __future__ import annotations

import copy

from leviathan.graphrag import verify as vf


# -- shared fixtures --------------------------------------------------------------------------------------
def _call(table, metric, value, unit, *, period=None, stamp=False, country=None):
    c = {"query": {"table": table, "metric": metric, "country": country},
         "rows": [{"period": period, "estimate_role": None, "value": value, "unit": unit, "country": country,
                   "knowledge_date": "2026-09-11"}], "status": "ok"}
    if stamp:
        c["display"] = "analyst"
    return c


def _pad(n, rows: dict, *, stamp=False) -> list:
    """A positional call list of length n with the served rows at their own [N] index."""
    out = [_call("silver_cot", "mm_net", 123456.0 + i, "contracts", stamp=stamp) for i in range(n)]
    for k, c in rows.items():
        c = copy.deepcopy(c)
        if stamp:
            c["display"] = "analyst"
        else:
            c.pop("display", None)
        out[k - 1] = c
    return out


def _run(tldr, calls, *, mechanism="", sources=None, evidence=None, **kw):
    st = {"tldr": tldr, "mechanism": mechanism, "sources": list(sources or [])}
    rep = vf.verify_citations(st, list(evidence or []), calls, **kw)
    return rep, st


# =========================================================================================================
# K7 -- THE RICE SIX-CHARGE CLASS (09-24 deep rice: number_unbacked 5 + number_mismatch 1, four TL;DR handles
# dropped). Served rows verbatim: N20 = the seat's su_ratio FRACTION (0.3556, no unit), N169 / N171 the
# board's level (27.31 %) and percentile (44), N64 / N66 area, N70 / N72 India exports.
# =========================================================================================================
_RICE = {
    20: _call("silver_psd", "su_ratio", "0.35556833429173856", None, period="2025", country="United States"),
    169: _call("silver_psd", "su_ratio", 27.309493401447426, "%", country="United States"),
    171: _call("silver_psd", "su_ratio", 44, "percentile", country="United States"),
    64: _call("silver_psd", "area_harvested_1000ha", 0.8320000000000001, "M ha", country="United States"),
    66: _call("silver_psd", "area_harvested_1000ha", 17, "percentile", country="United States"),
    70: _call("silver_psd", "exports_mt", 25.0, "MMT", country="India"),
    72: _call("silver_psd", "exports_mt", 99, "percentile", country="India"),
}
_RICE_TLDR = ("The US rice balance sheet has tightened over the past year but is not tight in absolute terms: the "
              "stocks-to-use ratio for 2026/27 is 27.31% [N169], at the 44th percentile of its own record [N171] "
              "and down from 35.5568% the prior marketing year [N20], with harvested area at 0.83 M ha [N64], the "
              "17th percentile of its own record [N66].")
_RICE_MECH = ("- Stocks-to-use: 27.31% for 2026/27 [N169] versus 35.5568% for 2025 [N20] \u2014 a real "
              "tightening, but still mid-record [N171].")


def test_k7_rice_the_six_charges_are_heads_on_an_unstamped_turn():
    """The control cell (no analyst stamp): HEAD's verdicts, reproduced -- the strike table's six charges."""
    rep, st = _run(_RICE_TLDR, _pad(212, _RICE), mechanism=_RICE_MECH)
    assert rep["by_rule"] == {"number_unbacked": 5, "number_mismatch": 1}
    assert "[N169]" not in st["tldr"] and "[N20]" in st["tldr"]


def test_k7_rice_the_stamped_turn_backs_the_card_scaled_figure_and_keeps_every_handle():
    rep, st = _run(_RICE_TLDR, _pad(212, _RICE, stamp=True), mechanism=_RICE_MECH)
    assert rep["by_rule"] == {} and rep["stripped"] == 0
    assert st["tldr"] == _RICE_TLDR and st["mechanism"] == _RICE_MECH


def test_k7_the_member_is_typed_by_the_written_unit_both_scales_backed():
    """V-3: the scaled member backs only a numeral written in the DISPLAY unit. "27.31 %" is backed
    across rows by the stamped fraction's display member; the same digits with no unit are charged
    exactly as on the unstamped turn; the fraction itself stays a member (both scales backed)."""
    frac = _call("silver_psd", "su_ratio", "0.27309493401447427", None, period="2026", country="United States")
    other = _call("silver_cot", "mm_net", 414460.0, "contracts")
    for stamp in (False, True):
        calls = _pad(2, {1: frac, 2: other}, stamp=stamp)
        with_unit = vf._check_number_handle("Funds hold 414,460 contracts [N2] against 27.31 % of use.", 2, calls)
        no_unit = vf._check_number_handle("Funds hold 414,460 contracts [N2] against 27.31 of use.", 2, calls)
        fraction = vf._check_number_handle("Funds hold 414,460 contracts [N2] against 0.2731 of use.", 2, calls)
        assert no_unit == "number_unbacked"                      # charged as today on both cells
        assert fraction is None                                  # the unscaled value stays a member
        assert with_unit == (None if stamp else "number_unbacked")


def test_k7_rounded_to_the_display_precision_the_cited_handle_is_not_mismatched():
    """"36 % [N20]" is 0.3556 x 100 rounded at the precision the writer wrote -- the reader-precision arm
    at the card's display scale (HEAD's x100 bridge is a 1 % window and refuses it)."""
    s = "Stocks-to-use was 36 % the prior year [N20]."
    assert vf._check_number_handle(s, 20, _pad(20, {20: _RICE[20]})) == "number_mismatch"
    assert vf._check_number_handle(s, 20, _pad(20, {20: _RICE[20]}, stamp=True)) is None
    assert vf._check_number_handle("Stocks-to-use was 36 the prior year [N20].", 20,
                                   _pad(20, {20: _RICE[20]}, stamp=True)) == "number_mismatch"


def test_k7_a_row_already_in_the_display_unit_or_in_another_unit_takes_no_member():
    """N169 is served in "%" already (no 2,730.9 member) and N171 is a percentile of the level (no x100 of
    44); only the unit-less fraction in the card's native unit gains a member."""
    assert vf._display_members(dict(_RICE[169], display="analyst")) == ()
    assert vf._display_members(dict(_RICE[171], display="analyst")) == ()
    vals, unit = vf._display_members(dict(_RICE[20], display="analyst"))
    assert unit == ("%",) and abs(vals[0] - 35.556833429173856) < 1e-9
    assert vf._display_members(_RICE[20]) == ()                 # unstamped: HEAD, no member


def test_k7_the_display_unit_types_the_binding():
    """"35.5568%" binds to the unit-less seat fraction whose card prints it in "%" -- not to the only "%"
    row in reach (the board's N169, another marketing year) -- once [N20] is stamped."""
    calls_s = _pad(212, _RICE, stamp=True)
    units = vf._row_units_of_group(vf._handle_groups("[N20]")[0], calls_s)
    assert ("%",) in units
    assert ("%",) not in vf._row_units_of_group(vf._handle_groups("[N20]")[0], _pad(212, _RICE))


def test_k7_palm_months_of_export_cover_is_a_display_unit_at_scale_one():
    palm = _call("silver_mpob", "su_ratio", 1.8923, "ratio")
    s = "Palm stocks cover 1.89 months of export cover [N1]."
    for stamp in (False, True):
        calls = _pad(1, {1: palm}, stamp=stamp)
        assert vf._check_number_handle(s, 1, calls) is None
    dm = vf._display_members(dict(palm, display="analyst"))
    assert dm and dm[1] == ("months", "of", "export", "cover")


# =========================================================================================================
# 28f -- THE CARD'S OWN THRESHOLD IS NOT A CLAIM (09-24 cocoa, the one "could not back" on ten pages).
# =========================================================================================================
_TAIL = _call("gold_weather_z", "tmax_anomaly_tail_share", 0.0, "%", country="West Africa")
_COT = _call("silver_cot", "mm_net", -9539.0, "contracts")
_COCOA_S2 = "no basin cell sits at or beyond +2 sigma on heat [N199]."


def _declare(monkeypatch, table="gold_weather_z", metric="tmax_anomaly_tail_share",
             phrases=("at or beyond +2 sigma",)):
    from leviathan.graphrag.numbers import registry as reg
    monkeypatch.setattr(reg, "definition_phrases",
                        lambda t, m: tuple(phrases) if (t, m) == (table, metric) else (), raising=False)


def test_28f_the_cocoa_threshold_is_masked_on_a_stamped_call_of_its_metric(monkeypatch):
    _declare(monkeypatch)
    rep, st = _run(_COCOA_S2, _pad(199, {199: _TAIL, 59: _COT}, stamp=True))
    assert rep["by_rule"] == {} and st["tldr"] == _COCOA_S2
    assert vf._check_number_handle(_COCOA_S2, 199, _pad(199, {199: _TAIL}, stamp=True)) is None


def test_28f_the_unstamped_turn_keeps_heads_charge(monkeypatch):
    _declare(monkeypatch)
    assert vf._check_number_handle(_COCOA_S2, 199, _pad(199, {199: _TAIL})) == "number_mismatch"


def test_28f_a_threshold_on_a_cot_row_is_charged_as_today(monkeypatch):
    """V-5: "+2 sigma [N59]" on a COT row -- no card of that metric declares it -> a claim, charged."""
    _declare(monkeypatch)
    calls = _pad(199, {199: _TAIL, 59: _COT}, stamp=True)
    assert vf._check_number_handle("managed money sits at or beyond +2 sigma [N59].", 59, calls) \
        == "number_mismatch"


def test_28f_the_phrase_must_bind_to_the_declaring_metric(monkeypatch):
    """Cited in the sentence is not enough: a second place the phrase is written, bound to the COT
    handle, keeps the phrase a claim everywhere in the sentence (fail closed)."""
    _declare(monkeypatch)
    calls = _pad(199, {199: _TAIL, 59: _COT}, stamp=True)
    s = ("no basin cell sits at or beyond +2 sigma on heat [N199], and managed money sits at or beyond "
         "+2 sigma [N59].")
    assert vf._check_number_handle(s, 59, calls) == "number_mismatch"
    assert vf._bound_definitions(s, calls, [199, 59], vf._grammar_for("x", calls)) == ()


def test_28f_no_declaration_no_mask():
    """Until the card declares the phrase (lane T's field), the stamped turn reads HEAD's claim."""
    calls = _pad(199, {199: _TAIL}, stamp=True)
    if not vf._card_definitions_of(calls[198]):
        assert vf._check_number_handle(_COCOA_S2, 199, calls) == "number_mismatch"


# =========================================================================================================
# K4 -- bind_figures, unit_family, unit_mismatch (09-24 corn/wheat, fact F8: "98 years' standing" bound to
# [N53], the 98th PERCENTILE of US corn harvested area).
# =========================================================================================================
_CW = {51: _call("silver_psd", "area_harvested_1000ha", 35.817, "M ha", country="United States"),
       53: _call("silver_psd", "area_harvested_1000ha", 98, "percentile", country="United States"),
       18: _call("silver_noaa_oni", "oni_anom", 1.8, "degC"),
       71: _call("silver_psd", "su_ratio", 12.139340211469118, "%", country="United States"),
       42: _call("silver_cot", "mm_net", 414460.0, "contracts"),
       44: _call("silver_cot", "mm_net", 100, "percentile")}
_CW_S = ("the two-sided part is that corn's own drivers lean both ways \u2014 the largest US corn harvested area "
         "in 98 years' standing of its own record [N51][N53] and a warm-phase Pacific reading past the strong "
         "line [N18] both point lower, while a tight buffer [N71] and record managed-money length [N42][N44] "
         "point higher.")


def test_k4_bind_figures_names_the_handle_the_written_unit_its_family_and_the_noun():
    out = vf.bind_figures(_CW_S, _pad(93, _CW, stamp=True))
    (e,) = [x for x in out if x["numeral"] == "98"]
    assert e["handle"] == 53 and not e["ambiguous"]
    assert e["unit_written"] == "years" and e["unit_family_written"] == "duration"
    assert _CW_S[e["noun_span"][0]:e["noun_span"][1]] == "the largest US corn harvested area in"
    assert _CW_S[e["span"][0]:e["span"][1]] == "98"
    assert set(e) >= {"handle", "numeral", "span", "unit_written", "unit_family_written", "noun_span"}


def test_k4_bind_figures_is_pure_and_changes_no_verdict():
    """V-4: a read-only wrapper -- the sentence, the calls and every verdict are the same with or without
    it having been called; `_bind` itself is untouched."""
    calls = _pad(93, _CW, stamp=True)
    before = copy.deepcopy(calls)
    r1, s1 = _run(_CW_S, copy.deepcopy(calls))
    vf.bind_figures(_CW_S, calls)
    assert calls == before
    r2, s2 = _run(_CW_S, copy.deepcopy(calls))
    assert r1 == r2 and s1 == s2
    assert vf.bind_figures(None, None) == [] and vf.bind_figures("no handles here 4.5", []) == []


def test_k4_unit_mismatch_is_reported_on_a_stamped_call_never_charged():
    rep_on, st_on = _run(_CW_S, _pad(93, _CW, stamp=True))
    rep_off, st_off = _run(_CW_S, _pad(93, _CW))
    (m,) = rep_on["unit_mismatch"]
    assert m["handle"] == 53 and m["unit_family_written"] == "duration" and m["unit_family_call"] == ["percentile"]
    assert "unit_mismatch" not in rep_off                       # the control cell: HEAD's report shape
    assert rep_on["by_rule"] == rep_off["by_rule"] and st_on == st_off   # counted, never charged


def test_k4_unit_family_reads_declared_data_and_refuses_to_guess():
    assert vf.unit_family("years") == "duration" and vf.unit_family("sessions") == "duration"
    assert vf.unit_family("percentile") == "percentile" and vf.unit_family("98th percentile".split()[1]) == "percentile"
    assert vf.unit_family("%") == "percent" and vf.unit_family("percent") == "percent"
    # a unit whose dimension no card declares is NOT classified: never a mismatch
    for u in ("1000 MT", "MMT", "US cents/bushel", "months of export cover", "ratio", "z", "contracts", ""):
        assert vf.unit_family(u) == "", u


def test_k4_the_written_unit_span_agrees_with_the_charge_reader():
    calls = _pad(93, _CW, stamp=True)
    g = vf._grammar_for(_CW_S, calls)
    masked = vf._mask_handles(_CW_S)
    for a, b, _v, _d, _k in vf._written_figures(masked, g):
        toks, u0, u1 = vf._unit_written_span(masked, b, g)
        assert toks == vf._unit_written_at(masked, b, g)


# =========================================================================================================
# K1 -- ADDRESS-FIRST RESOLUTION FROM THE ONE LEDGER. The 09-24 tariff turn: fabricated_citation 5 (E23,
# E24, E25, E26, E46) + ledger_cascade 6 -- E23-E26 real menu documents whose 09-23 twins resolved. The
# menu is rebuilt from the documents the 09-23 trace resolved (`citation_resolved` snippets, verbatim).
# =========================================================================================================
def _doc(source, date, text, key, **kw):
    return dict({"source": source, "date": date, "text": text, "source_key": key}, **kw)


def _tariff_menu() -> list:
    ev = [_doc("usda_wasde", "2019-01-01", "Placeholder market text about wheat planting in Kansas.", "p%d" % i)
          for i in range(48)]
    ev[1] = _doc("mpoc", "2021-02-04", "On 6th July 2018, China imposed a 25% additional tariff on US soybean "
                 "imports on top of the normal 3% tax paid.", "mpoc/2021-02-04")
    ev[2] = _doc("usda_wasde", "2018-07-12", "China has recently imposed soybean import duties affecting U.S. "
                 "soybean and product trade for 2018/19.", "wasde/2018-07-12")
    ev[22] = _doc("usda_gain_rapeseed", "2022-03-17", "China implemented a tariff exclusion process on March 2, "
                  "2020, for Section 301 retaliatory tariffs on U.S. soybeans, returning duties from 3",
                  "gain_rapeseed/CN/20220317")
    ev[23] = _doc("usda_gain_soybean_meal", "2022-03-17", "China implemented a tariff exclusion process on "
                  "March 2, 2020, for Section 301 retaliatory tariffs on U.S. soybeans, reducing effective duti",
                  "gain_soybean_meal/CN/20220317")
    ev[25] = _doc("usda_gain_corn", "2020-04-09", "On February 18, 2020, China announced a new round of tariff "
                  "exclusions for U.S. agricultural commodities impacted by the retaliatory Section",
                  "gain_corn/CN/20200409")
    ev[45] = _doc("usda_gain_soybeans", "2025-03-19", "Beijing has placed retaliatory tariffs on U.S. "
                  "soybeans.", "gain_soybeans/CN/20250319", event_date="2025-03-01",
                  event_date_precision="month")
    return ev


_TARIFF_MECH = ("Effective duties stood at 30.5 percent until 2 March 2020, when China opened an exclusion "
                "process returning them to 3 percent [E23][E24], following a first exclusion round announced "
                "18 February 2020 [E26].")
# the declared spellings the fact grader's repro shows convict at HEAD (0 same-source items)
_TARIFF_SOURCES = [{"ref": 23, "source": "USDA FAS GAIN Report - Rapeseed", "date": "2022-03-17"},
                   {"ref": 24, "source": "USDA FAS GAIN Report - Soybean Meal", "date": "2022-03-17"},
                   {"ref": 26, "source": "USDA FAS GAIN Report - Corn", "date": "2020-04-09"}]


def test_k1_absent_kwarg_is_heads_path_the_tariff_declarations_convict():
    rep, st = _run("", [], mechanism=_TARIFF_MECH, sources=_TARIFF_SOURCES, evidence=_tariff_menu())
    assert rep["by_rule"] == {"fabricated_citation": 3, "ledger_cascade": 3}
    assert "[E23]" not in st["mechanism"] and "ledger_declared_mismatch" not in rep


def _iss(ev, *ks, extra=None) -> dict:
    """The ledger's `issued()` map for a block that printed addresses `ks` (the fixer pass's K1 amendment,
    REVIEW_VC F1): {k: [the address's own row, every other chunk shown under k]}. Only its KEYS are issued."""
    out = {k: [ev[k - 1]] for k in ks}
    for k, ch in (extra or {}).items():
        out[k] = [ev[k - 1]] + list(ch)
    return out


def test_k1_a_declaration_by_the_pages_display_name_names_its_document():
    """The tariff chronology (09-24 fabricated 3 + cascade 3 at HEAD): the writer declared E23 / E24 / E26 by
    the name the PAGE prints for them ("USDA FAS GAIN Report - Rapeseed" for `usda_gain_rapeseed`,
    `display.source_name`) with each document's own date. On a board turn (the kwarg present) the display
    name is an identity of the source, so the three resolve to their own documents whether or not the block
    printed them -- through HEAD's matcher, never by correcting a declaration onto an address."""
    ev = _tariff_menu()
    for chunks in ({46: [ev[45]]}, _iss(ev, 23, 24, 26)):
        rep, st = _run("", [], mechanism=_TARIFF_MECH, sources=copy.deepcopy(_TARIFF_SOURCES), evidence=ev,
                       evidence_chunks=chunks)
        assert rep["by_rule"] == {} and st["mechanism"] == _TARIFF_MECH, chunks.keys()
        assert sorted(rep["resolved"]) == ["23", "24", "26"]
        assert rep["resolved"]["23"]["source_key"] == "gain_rapeseed/CN/20220317"
        assert rep["resolved"]["26"]["source_key"] == "gain_corn/CN/20200409"
        assert "ledger_declared_mismatch" not in rep and rep["corrected"] == 0


def test_k1_an_issued_address_corrects_a_declaration_that_names_no_other_document():
    """A declaration at an ISSUED address whose date disagrees with the address and names no OTHER document
    exactly is corrected to the address's own (the footer's row), reported in `ledger_declared_mismatch`."""
    ev = _tariff_menu()
    src = [{"ref": 23, "source": "USDA FAS GAIN Report - Rapeseed", "date": "2022-03-18"}]
    s = "China opened a tariff exclusion process for U.S. soybeans on 2 March 2020 [E23]."
    rep, st = _run(s, [], sources=src, evidence=ev, evidence_chunks=_iss(ev, 23))
    assert rep["by_rule"] == {} and rep["resolved"]["23"]["source_key"] == "gain_rapeseed/CN/20220317"
    assert rep["ledger_declared_mismatch"]["23"]["declared"]["date"] == "2022-03-18"
    assert {x["ref"]: x["date"] for x in st["sources"]}[23] == "2022-03-17" and rep["corrected"] == 1


def test_k1_f1b_an_index_slip_resolves_to_the_document_the_declaration_names():
    """REVIEW_VC F1 (b), the real 09-23 rice E41 shape: the writer declares the TRUE document (its source and
    date, as it saw them) but types a NEIGHBOUR's index -- here the issued address 46. The declaration names
    ONE other document exactly, so it is an index slip: the ref resolves to the document it names (HEAD's
    matcher), never "corrected" onto the address it mistyped."""
    ev = _tariff_menu()
    src = [{"ref": 46, "source": "usda_gain_rapeseed", "date": "2022-03-17"}]
    s = "China implemented a tariff exclusion process for U.S. soybeans on 2 March 2020 [E46]."
    rep, st = _run(s, [], sources=src, evidence=ev, evidence_chunks=_iss(ev, 46))
    assert rep["resolved"]["46"]["source_key"] == "gain_rapeseed/CN/20220317"
    assert "ledger_declared_mismatch" not in rep and rep["by_rule"] == {} and "[E46]" in st["tldr"]
    rep_h, _ = _run(s, [], sources=src, evidence=ev)                   # HEAD: the same document
    assert rep_h["resolved"]["46"]["source_key"] == "gain_rapeseed/CN/20220317"


def test_k1_fabricated_citation_is_reserved_for_a_ref_the_ledger_never_issued():
    ev = _tariff_menu()
    src = [{"ref": 60, "source": "China State Council Tariff Commission", "date": "2025-03-04"}]
    rep, _st = _run("Beijing announced tariffs on soybeans [E60].", [], sources=src, evidence=ev,
                    evidence_chunks=_iss(ev, 46))
    assert rep["by_rule"] == {"fabricated_citation": 1, "ledger_cascade": 1}


def test_k1_v1_the_writer_named_another_document_the_address_must_support_the_sentence():
    """V-1: a declaration naming another document that is NOT exactly one the turn holds (the date names no
    rapeseed report) resolves to the ISSUED address, and the address must carry the sentence on its own
    chunks -- the placeholder at [E5] shares nothing, so the handle goes (visible), the sentence stays."""
    ev = _tariff_menu()
    src = [{"ref": 5, "source": "USDA FAS GAIN Report - Rapeseed", "date": "2021-01-01"}]
    s = "China opened an exclusion process returning duties to 3 percent [E5]."
    rep, st = _run(s, [], sources=src, evidence=ev, evidence_chunks=_iss(ev, 5))
    assert rep["by_rule"] == {"unsupported_at_address": 1}
    assert st["tldr"] == "China opened an exclusion process returning duties to 3 percent."


def test_k1_v2_a_day_the_address_never_dated_convicts_the_date_even_beside_the_report_date():
    """V-2 (the tariff E46 shape): [E46] declared "2025-02-01" on a document dated 2025-03-19 whose event is
    month-precision March 2025. The declaration is corrected to the address's own date (the footer's row);
    a sentence writing the day "1 February 2025" is a date the store never dated -> `date_contradiction`,
    handle dropped, words kept -- and a report date written beside it does not launder it."""
    ev = _tariff_menu()
    src = [{"ref": 46, "source": "USDA FAS GAIN", "date": "2025-02-01"}]
    ok = "Beijing has placed retaliatory tariffs on U.S. soybeans, reported 19 March 2025 [E46]."
    bad = ("Beijing announced 10 to 15 percent more tariffs on US agricultural products, 10 percent on "
           "soybeans, on 1 February 2025 [E46], reported 19 March 2025.")
    rep, st = _run(ok + " " + bad, [], sources=src, evidence=ev, evidence_chunks=_iss(ev, 46))
    assert rep["by_rule"] == {"date_contradiction": 1}
    assert rep["resolved"]["46"]["date"] == "2025-03-19"
    assert rep["ledger_declared_mismatch"]["46"]["declared"]["date"] == "2025-02-01"
    assert st["tldr"].count("[E46]") == 1 and "on 1 February 2025, reported" in st["tldr"]
    # HEAD (no kwarg): the declaration is the retry's single-document correction and the report date
    # launders the day ("any" bound date fits)
    rep_h, _ = _run(ok + " " + bad, [], sources=src, evidence=ev)
    assert "date_contradiction" not in rep_h["by_rule"]


def test_k1_v2_a_day_precision_event_carries_its_day():
    ev = _tariff_menu()
    ev[45] = dict(ev[45], event_date="2025-03-04", event_date_precision="day")
    s = "China announced tariffs of 10 percent on U.S. soybeans on 4 March 2025 [E46]."
    rep, st = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 46))
    assert rep["by_rule"] == {} and "46" in rep["resolved_undeclared"]


def test_k1_f1_an_issued_address_resolves_by_an_identity_the_block_printed_or_by_winning_the_menu():
    """REVIEW_VC F1 + M4. The block prints every receipt with its date, so an undeclared [Ek] the ledger
    ISSUED resolves when the sentence carries that identity (a bound date the address carries, its own date
    echoed, a shared claim magnitude) or is closer to it than to any other document the turn holds (HEAD's
    clause (iii)). A sentence a same-topic NEIGHBOUR backs better, with no identity of the address, is
    `unsupported_at_address` -- handle off, sentence kept -- never a footer row naming the wrong document."""
    ev = [_doc("usda_gain_cocoa", "2025-03-07", "Harmattan winds and a lack of rainfall have been raising "
               "concerns in Cote d'Ivoire.", "gain_cocoa/CI/20250307"),
          _doc("usda_gain_cocoa", "2025-08-22", "Prolonged drought conditions in West Africa began in April "
               "2024, contributing to a weaker cocoa crop; drought conditions and Harmattan winds hurt "
               "yields.", "gain_cocoa/BR/20250822")]
    s = "Harmattan winds and drought conditions hurt the West Africa crop [E1]."
    rep, st = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 1))
    assert rep["by_rule"] == {"unsupported_at_address": 1} and "resolved_undeclared" not in rep
    dated = "Harmattan winds and drought conditions hurt the West Africa crop, reported 7 March 2025 [E1]."
    rep_d, st_d = _run(dated, [], evidence=ev, evidence_chunks=_iss(ev, 1))
    assert rep_d["by_rule"] == {} and rep_d["resolved_undeclared"]["1"]["source_key"] == "gain_cocoa/CI/20250307"
    own = "Harmattan winds and a lack of rainfall raised concerns in Cote d'Ivoire [E1]."
    rep_o, _ = _run(own, [], evidence=ev, evidence_chunks=_iss(ev, 1))
    assert rep_o["by_rule"] == {} and "1" in rep_o["resolved_undeclared"]


def test_k1_f1a_a_menu_index_the_block_never_printed_takes_heads_resolution():
    """REVIEW_VC F1 (a): the address-first rule reads the ISSUED set, never the index range. [E7] is a menu
    placeholder the block did not print: the writer's plain citation keeps HEAD's reading (kept, then the
    footer's own prune) on a board turn exactly as on a control turn; issued, it is charged."""
    ev = _tariff_menu()
    s = "China opened an exclusion process returning duties to 3 percent [E7]."
    rep_h, st_h = _run(s, [], evidence=ev)
    assert rep_h["by_rule"] == {} and "[E7]" in st_h["tldr"]       # HEAD: silent keep (then the prune)
    rep_p, st_p = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 46))
    assert (rep_p["by_rule"], st_p["tldr"]) == (rep_h["by_rule"], st_h["tldr"])
    assert "resolved_undeclared" not in rep_p
    rep, st = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 7))
    assert rep["by_rule"] == {"unsupported_at_address": 1}
    assert st["tldr"] == "China opened an exclusion process returning duties to 3 percent."


def test_k1_c1_the_chunk_union_backs_a_sentence_quoting_the_boards_chunk():
    """C-1: address k shows two texts (the menu chunk and the board receipt's chunk of the same document)."""
    ev = _tariff_menu()
    chunk2 = dict(ev[45], text="In March 2025 China announced additional tariffs of 10 to 15 percent on U.S. "
                  "agricultural products, including 10 percent on soybeans.")
    s = "Agricultural products drew additional duties of 10 to 15 percent in March 2025 [E46]."
    rep_menu_only, _ = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 46))
    assert rep_menu_only["by_rule"] == {"unsupported_at_address": 1}
    rep, st = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, extra={46: [chunk2]}))
    assert rep["by_rule"] == {} and "46" in rep["resolved_undeclared"]
    neither = "Brazil planted a record soybean area [E46]."
    rep_n, _ = _run(neither, [], evidence=ev, evidence_chunks=_iss(ev, extra={46: [chunk2]}))
    assert rep_n["by_rule"] == {"unsupported_at_address": 1}


def test_k1_a_quote_a_co_cited_address_carries_backs_the_sentence():
    """A two-source sentence: each issued address is compared only against the documents the sentence does
    NOT itself cite (a co-cited document is accounted for by its own handle)."""
    ev = _tariff_menu()
    s = ('The tariff history is plain: "China imposed a 25% additional tariff on US soybean imports" [E2] '
         'and duties affected U.S. soybean trade [E3].')
    rep, _ = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 2, 3))
    assert rep["by_rule"] == {} and sorted(rep["resolved_undeclared"]) == ["2", "3"]
    bad = 'Officials said "tariffs will rise to forty percent next quarter" on soybean imports [E3].'
    rep_b, _ = _run(bad, [], evidence=ev, evidence_chunks=_iss(ev, 2, 3))
    assert rep_b["by_rule"] == {"quote_mismatch": 1}


def test_k1_grouped_addresses_resolve_for_the_footer_and_are_never_charged():
    ev = _tariff_menu()
    s = "China opened an exclusion process on 2 March 2020 [E23, E24, E7]."
    rep, st = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 23, 24, 7))
    assert rep["by_rule"] == {} and st["tldr"] == s
    assert sorted(rep["resolved_undeclared"]) == ["23", "24"]


def test_k1_a_number_declaration_stays_a_number_declaration():
    calls = [_call("silver_psd", "su_ratio", 12.14, "%")]
    src = [{"ref": 1, "source": "USDA PSD", "date": "2026-09-11"}]
    ev = _tariff_menu()
    rep, st = _run("The US stocks-to-use ratio reads 12.14 % [N1].", calls, sources=src, evidence=ev,
                   evidence_chunks=_iss(ev, 1))
    assert rep["by_rule"] == {} and "1" not in rep["resolved"] and "ledger_declared_mismatch" not in rep


def test_k1_a_ledger_that_issued_nothing_reads_heads_bytes_when_the_kwarg_is_absent():
    """The absent kwarg is HEAD's call exactly: report and prose equal to a run that never heard of it."""
    ev = _tariff_menu()
    s = "China has recently imposed soybean import duties [E3] and a 25% tariff [E2]."
    r1, s1 = _run(s, [], mechanism=_TARIFF_MECH, sources=_TARIFF_SOURCES, evidence=ev)
    r2, s2 = _run(s, [], mechanism=_TARIFF_MECH, sources=_TARIFF_SOURCES, evidence=ev, evidence_chunks=None)
    assert r1 == r2 and s1 == s2


def test_k1_m4_no_stop_list_the_identity_is_structural():
    """REVIEW_VC M4: the first cut's `_grammar_words` (a month-name + unit-spelling stop list tuning a word
    test) is RETIRED. The same measured twins are refused structurally: a tariff-exclusion sentence swapped
    onto a cocoa Harmattan document (sharing "february") or a Ghana grindings document (sharing "percent")
    loses the menu to the document that states its own claim magnitude, which resolves on that identity."""
    ev = [_doc("usda_gain_cocoa", "2025-03-07", "Since December 2024 and into February 2025, Harmattan winds "
               "with a lack of suboptimal rainfall have been raising concerns", "gain_cocoa/CI"),
          _doc("usda_gain_cocoa", "2025-12-03", "Ghana's projected domestic cocoa grindings for MY 2025/2026 "
               "represent a 36 percent increase from the preceding market year's estimate", "gain_cocoa/GH"),
          _doc("usda_gain_rapeseed", "2022-03-17", "returning duties from 30.5 percent", "gain_rapeseed/CN")]
    s = ("Effective duties stood at 30.5 percent until March 2020, following a first exclusion round announced "
         "in February 2020 [E%d].")
    for k in (1, 2):
        rep, _ = _run(s % k, [], evidence=ev, evidence_chunks=_iss(ev, 1, 2, 3))
        assert rep["by_rule"] == {"unsupported_at_address": 1}, k
    rep, _ = _run(s % 3, [], evidence=ev, evidence_chunks=_iss(ev, 1, 2, 3))
    assert rep["by_rule"] == {}
    assert not hasattr(vf, "_grammar_words")
    # the true citations the stop list DROPPED (REVIEW_VC F1: the only anchor a month or a unit word) resolve
    ev2 = [_doc("mpoc", "2024-09-02", "Indonesia cut its export levy in September 2024 to 7.5 percent.", "a"),
           _doc("usda_wasde", "2019-01-01", "Wheat planting in Kansas was slow.", "b")]
    for s2 in ("The September 2024 levy reduction [E1] eased Indonesian export costs.",
               "Roughly 40 percent of the levy was cut [E1]."):
        rep2, _ = _run(s2, [], evidence=ev2, evidence_chunks=_iss(ev2, 1))
        assert rep2["by_rule"] == {} and "1" in rep2["resolved_undeclared"], s2


def test_k1_b15_the_real_ledger_round_trip():
    """B15 (ii)/(iii) with lane C's EvidenceLedger: a registered receipt and a second chunk of a menu document
    resolve at their issued addresses; a ledger that issued nothing is the menu, byte for byte."""
    import pytest
    from leviathan.graphrag import citations as cit
    led_cls = getattr(cit, "EvidenceLedger", None)
    if led_cls is None:
        pytest.skip("lane C's EvidenceLedger not in the tree")
    menu = [_doc("usda_wasde", "2018-07-12", "China has recently imposed soybean import duties affecting U.S. "
                 "soybean and product trade for 2018/19.", "wasde/2018"),
            _doc("usda_gain_soybeans", "2025-03-19", "Beijing has placed retaliatory tariffs on U.S. soybeans.",
                 "gain_soybeans/CN/20250319")]
    led = led_cls(copy.deepcopy(menu))
    assert led.evidence() == menu
    k_chunk = led.address(_doc("usda_gain_soybeans", "2025-03-19", "China announced that it will impose an "
                               "additional 10 percent more tariffs on soybeans imported from the United States "
                               "starting on March 10", "gain_soybeans/CN/20250319"))
    k_new = led.address(_doc("usda_wap", "2012-09-01", "A severe La Nina drought reduced soybean yields by more "
                             "than 30 percent in the southern state of Parana, Brazil", "wap/2012-09-01"))
    assert (k_chunk, k_new) == (2, 3)
    ev, ch = led.evidence(), (led.issued() if hasattr(led, "issued") else led.chunks())
    s1 = "An additional 10 percent tariff on imported soybeans started on 10 March 2025 [E2]."
    s2 = "A severe drought reduced soybean yields in Parana, Brazil [E3]."
    rep, st = _run(s1 + " " + s2, [], evidence=ev, evidence_chunks=ch)
    assert rep["by_rule"] == {} and sorted(rep["resolved_undeclared"]) == ["2", "3"]


def test_k7_c5_one_row_backed_at_both_scales_on_its_own_handle():
    """THREAT_MODEL C-5 (lane C prints the seat su_ratio row at the card's display spec): the label's
    "10.72 %" and the raw "0.1072" both back on the row's own handle; a figure off both scales is charged."""
    su = _call("silver_psd", "su_ratio", "0.10719961351182984", None, period="2026", country="United States")
    calls = _pad(9, {9: su}, stamp=True)
    for s in ("The US stocks-to-use ratio is 10.72 % of domestic use, 2026/27 [N9].",
              "The US stocks-to-use ratio is 0.1072 for 2026/27 [N9].",
              "The US stocks-to-use ratio is 10.7 % [N9]."):
        assert vf._check_number_handle(s, 9, calls) is None, s
    assert vf._check_number_handle("The US stocks-to-use ratio is 12.5 % [N9].", 9, calls) == "number_mismatch"


def test_k4_a_figure_the_bound_call_does_not_carry_is_a_misaddress_not_a_unit_slip():
    """The unseen-corpus census (1,099 answers, calls stamped): 5 of 6 unit-family fires were a same-row
    percentile written beside the LEVEL's handle -- 09-23 rice, verbatim: "27.31% [N52], at the 44th
    percentile of its own record". 44 is not [N52]'s figure, so no unit was mis-written; rewriting it would
    print "the 44th %". Reported only when the bound call backs the value (`backed`)."""
    lvl = _call("silver_psd", "su_ratio", 27.309493401447426, "%", country="United States")
    s = ("the US stocks-to-use ratio sits at 27.31% [N52], at the 44th percentile of its own record and falling "
         "over the last marketing year.")
    rep, _ = _run(s, _pad(52, {52: lvl}, stamp=True))
    assert "unit_mismatch" not in rep
    (e,) = [x for x in vf.bind_figures(s, _pad(52, {52: lvl}, stamp=True)) if x["numeral"].startswith("44")]
    assert e["handle"] == 52 and e["backed"] is False and e["unit_family_written"] == "percentile"


def test_k1_a_dropped_address_leaves_no_resolution_behind():
    """An undeclared address whose handle PASS 1b drops (a quote no cited address carries) is not reported
    in `resolved_undeclared`, so no footer row outlives its citation."""
    ev = _tariff_menu()
    s = 'Beijing said "tariffs will rise to forty percent next quarter" on American soybeans [E46].'
    rep, st = _run(s, [], evidence=ev, evidence_chunks=_iss(ev, 46))
    assert rep["by_rule"] == {"quote_mismatch": 1} and "[E46]" not in st["tldr"]
    assert "46" not in (rep.get("resolved_undeclared") or {})


def test_k1_f1b_the_most_specific_source_identity_names_the_document():
    """FIXER SELF-REFUTATION (the F1 twin drive's DECL cell, 14 of 28,328 declared twins): one Brazil sugar
    report filed under two store partitions -- `usda_gain_sugar_semiannual` at E4 and `usda_gain_sugar` at
    the issued address E5, same date. The writer declared the SEMIANNUAL partition and typed 5. HEAD's
    containment rule reads "usda_gain_sugar" inside "usda_gain_sugar_semiannual", so the first cut judged
    the declaration to agree with the address and never ran the slip test. The declared source IS an item's
    id, so it names that item: an index slip, resolved to the document the writer named, as HEAD does."""
    txt = "In MY 2009/10 mills showed a preference for sugar over ethanol in Brazil."
    ev = [_doc("usda_wasde", "2019-01-01", "Placeholder market text about wheat planting in Kansas.", "p%d" % i)
          for i in range(6)]
    ev[3] = _doc("usda_gain_sugar_semiannual", "2009-10-19", txt, "semi/BR/20091019")
    ev[4] = _doc("usda_gain_sugar", "2009-10-19", txt, "sugar/BR/20091019")
    src = [{"ref": 5, "source": "usda_gain_sugar_semiannual", "date": "2009-10-19"}]
    s = "In MY 2009/10 mills swung back toward sugar over ethanol [E5]."
    rep_h, _ = _run(s, [], sources=copy.deepcopy(src), evidence=ev)
    rep, st = _run(s, [], sources=copy.deepcopy(src), evidence=ev, evidence_chunks=_iss(ev, 4, 5))
    assert rep_h["resolved"]["5"]["source_key"] == "semi/BR/20091019"
    assert rep["resolved"]["5"]["source_key"] == "semi/BR/20091019" and "[E5]" in st["tldr"]
    # ...and a declaration whose source only CONTAINS the address's, with no item carrying it as its id,
    # still agrees with the address (HEAD's containment rule is the fallback tier)
    src2 = [{"ref": 5, "source": "usda_gain_sugar_report", "date": "2009-10-19"}]
    rep2, _ = _run(s, [], sources=copy.deepcopy(src2), evidence=ev, evidence_chunks=_iss(ev, 4, 5))
    assert rep2["resolved"]["5"]["source_key"] == "sugar/BR/20091019"
