"""LANE I (fix sitting 2, 2026-09-26) -- THE EVAL INSTRUMENTS THAT CANNOT FAIL OR CANNOT SEE.

THE DEFECT CLASS, measured on 50 banked pages by the completeness recon: `n_sections` 0 on 50 of 50,
`intent_ok` False on 50 of 50, `tldr_direction.agree` True on 50 of 50, `coverage.watch_cited` 0 on 40 of 40
and `events_referenced` 0 on 40 of 40, the register precondition quoting `register_leaks` 0 on both cells
while `register.desk_register_hits` found 53 hits on 9 of 10 control pages, and no reader comparing a count
the page spelled out with the counter the trace minted for it.

THE PINS: every instrument reads ABSENT (None) where its producer field is not on the record -- never 0,
never False; a deck of >= 5 VARIED pages reads VARIED values on every re-based instrument; an instrument
that reads one value on every page is named VACUOUS and never quoted; every report line states its
population and its denominator; and the per-answer record's columns are HEAD's exactly (the census rides
the baseline JSON as one key appended after `per_answer`).

EVERY FIXTURE HERE IS SYNTHETIC. The per-answer records are built from the SHAPE of a banked record (id,
strips, claim_count, intent, intent_ok, tldr_direction, state_board{counters, coverage, chains,
chain_counts, analogs, row_states}, raw_draft, register_leaks, synth_usage, turn_cost_usd) and NO figure in
them is a real reading of any market: the counts, handles, costs and prose are invented to exercise the
instruments and must never be quoted as measurements.
"""
from __future__ import annotations

import json
import re

from leviathan.graphrag import eval as gev
from leviathan.graphrag.state.rows import words_for_int

# -- SYNTHETIC fixtures -------------------------------------------------------------------------------------
_HEADINGS = ("## Mechanism", "## The record", "## Where the record disagrees", "## What to watch",
             "## Outlook", "## Episodes")
_DECLARED = ("higher", "higher", "higher", "lower", "lower", "lower")
_SIDES = (("for", "for", "against"), ("against", "against", "for"), ("for", "for", "for"),
          ("against", "for", "against"), ("for", "against", "for"), ("against", "against", "against"))


def _chains(sides) -> list:
    """SYNTHETIC `state_board.chains` rows: only the fields the census reads, plus one unrendered chain
    whose side must never count (the page did not carry it)."""
    rows = [{"contract": "syn_market", "rendered": True, "side": s,
             "direction": {"for": "higher", "against": "lower"}.get(s, "unsettled")} for s in sides]
    return rows + [{"contract": "syn_market", "rendered": False, "side": "against", "direction": "lower"}]


def _banked(i: int) -> dict:
    """SYNTHETIC per-answer record number `i` of a VARIED six-page deck (banked shape: no served body, the
    writer's post-verify draft in `raw_draft`)."""
    seqs = 100 + i
    heads = "\n\n".join(f"{h}\nSynthetic body line {k}." for k, h in enumerate(_HEADINGS[: i + 1]))
    cite = " ".join(f"[N{40 + i + 10 * k}]" for k in range(i % 3))       # cites 0, 1 or 2 watch handles
    count_line = (f"{words_for_int(seqs)} chains of cause reach four markets" if i % 2 == 0
                  else f"eight chains of cause reach four markets")        # odd pages print a stale count
    desk = " The board reads this row high." if i in (1, 3, 4) else ""
    mech = f"{heads}\n\nThe watch lines hold {cite}. In all, {count_line}.{desk}"
    return {
        "id": f"syn_{i}", "strips": i % 2, "claim_count": 10 + i, "intent": "hybrid",
        "intent_ok": i not in (1, 4),
        "kind_history": ["plan:None->reasoning", "family_facet:reasoning->hybrid"],
        # the PRODUCER's flag reads True on every page (two_sided basis) -- the vacuous read this lane names
        "tldr_direction": {"basis": "two_sided", "tldr": "higher", "agree": True, "declared": _DECLARED[i]},
        "state_board": {
            "counters": {"BoardFired": 1, "BoardStateRows": 12 + i},
            "coverage": {"loud_rows": 5, "loud_cited": 2, "watch_rows": 2, "watch_cited": 0,
                         "watch_referenced": i % 3, "events_open": 1, "events_referenced": 0},
            "chains": _chains(_SIDES[i]),
            "chain_counts": {"total": 500 + i, "rendered": 3, "distinct_sequences": seqs,
                             "distinct_markets": 4, "history_n": [8, 3], "slot_state": {"pair": "seated"}},
            "analogs": [{"driver_id": "syn_driver", "n_candidates": 150 + i, "n_candidates_head": 3}],
            "row_states": [{"contract": "syn_market", "driver_id": "syn_driver", "z": 1.0 + i}],
            "watch_rows": [{"handle": 40 + i}, {"handle": f"N{50 + i}"}],
        },
        "raw_draft": {"postverify_tldr": f"Synthetic TL;DR {i}.", "postverify_mechanism": mech},
        "register_leaks": (0, 1, 0, 2, 0, 0)[i],
        **({"desk_register": {"outcome": "ok", "hits_before": 2, "hits_after": 1}} if i >= 3 else
           {"desk_register": None}),
        "synth_usage": {"model": "synthetic-model", "in": 1000 + i, "out": 200, "cache_read": 0,
                        "cache_write": 0},
        "turn_cost_usd": None,
    }


def _banked_deck() -> list:
    return [_banked(i) for i in range(6)]


def _absent_deck() -> list:
    """SYNTHETIC records on which every producer field the census reads is ABSENT."""
    return [{"id": f"abs_{i}", "strips": 0, "claim_count": 0, "intent": None, "intent_ok": None,
             "tldr_direction": None, "state_board": None, "raw_draft": None, "synth_usage": None,
             "turn_cost_usd": None} for i in range(6)]


def _live(rid, *, answer="", structured=None, intent="hybrid", expected="reasoning", kind_history=None,
          trace=None) -> dict:
    """A SYNTHETIC live row (q / out / rubric), scored by the shipped `score`."""
    q = {"id": rid, "contract": "corn", "question": "synthetic", "expected_intent": expected}
    out = {"answer": answer, "contract": "corn", "intent": intent, "structured": structured,
           "evidence": [], "citations": [], "number_calls": [], "trace": dict(trace or {})}
    if kind_history is not None:
        out["intent_decision"] = {"kind_history": list(kind_history)}
    return {"q": q, "out": out, "rubric": gev.score(q, out), "secs": 1.0}


# -- 1. n_sections: the RENDERED page, and ABSENT where no page was served ------------------------------------
def test_n_sections_counts_the_headings_the_served_body_rendered():
    body = "## Mechanism\nA.\n\n## The record\nB.\n\n```\n## not a heading, inside a fence\n```\n\n## Sources\n[N1]"
    rec = gev._per_answer_record(_live("r1", answer=body, structured={"tldr": "t", "mechanism": "m"}), "single")
    assert rec["n_sections"] == 3                  # was 0: structured['sections'] is never filled when served


def test_n_sections_is_absent_never_zero_when_no_page_and_no_sections_exist():
    rec = gev._per_answer_record({"q": {"id": "r0"}, "out": {}}, "single")
    assert rec["n_sections"] is None              # was 0 -- a fabricated zero for a page that does not exist


# -- 2. intent_ok: the router's OWN vocabulary -------------------------------------------------------------
def test_intent_ok_reads_every_word_of_the_routers_own_route():
    promoted = _live("p", kind_history=["plan:None->reasoning", "family_facet:reasoning->hybrid"])
    assert promoted["rubric"]["intent_ok"] is True           # was False: a DECLARED promotion is not a miss
    accept_set = _live("s", expected=["reasoning", "hybrid"])
    assert accept_set["rubric"]["intent_ok"] is True         # was False: a list compared with a string
    no_route = _live("n", intent=None)
    assert no_route["rubric"]["intent_ok"] is None           # was False: the router emitted nothing
    miss = _live("m", expected="numbers_only", kind_history=["plan:None->hybrid"])
    assert miss["rubric"]["intent_ok"] is False              # a real disagreement still FAILS


def test_a_word_the_router_emitted_on_no_row_is_a_vocabulary_mismatch_never_a_fail():
    rows = [_live(f"v{i}", kind_history=["plan:None->hybrid"]) for i in range(5)]
    assert all(r["rubric"]["intent_ok"] is False for r in rows)     # the per-row read cannot see the deck
    cen = gev.instrument_census(rows=rows)
    assert cen["census"]["intent_ok"]["n"] == 0                     # NOT 0 of 5 routed correctly
    assert cen["intent_vocabulary"]["unmatched_words"] == ["reasoning"]
    assert len(cen["intent_vocabulary"]["mismatched_rows"]) == 5
    rep = "\n".join(gev.instrument_report(cen))
    assert "VOCABULARY MISMATCH" in rep and "never scored as a routing fail" in rep
    # ...and a deck on which the router DID emit the word elsewhere keeps a real fail as a fail
    rows.append(_live("v5", kind_history=["plan:None->reasoning"]))
    cen2 = gev.instrument_census(rows=rows)
    assert cen2["census"]["intent_ok"]["n"] == 6 and cen2["census"]["intent_ok"]["value"] == 1


# -- 3. tldr_direction: the DECLARED token against the board's SETTLED sides ---------------------------------
def test_tldr_direction_is_absent_without_the_declared_token_whatever_the_producer_flag_says():
    rec = _banked(0)
    rec["tldr_direction"] = {"basis": "two_sided", "tldr": "higher", "agree": True}   # no `declared`
    got = gev._tldr_direction_read(rec)
    assert got["v"] is None and "declared" in got["why"]         # never the phrase match, never `agree`


def test_tldr_direction_never_reads_prose_and_takes_the_settled_side_by_precedence():
    rec = _banked(0)                                              # chains: for, for, against -> higher
    rec["tldr_direction"]["tldr"] = "lower"                        # a phrase match's verdict moves nothing
    rec["raw_draft"]["postverify_tldr"] = "My lean is modestly toward lower prices; not bullish."
    assert gev._tldr_direction_read(rec)["v"] is True
    rec["tldr_direction"]["declared"] = "lower"
    assert gev._tldr_direction_read(rec)["v"] is False
    rec["state_board"]["row_states"][0]["side"] = "against"        # rung 2 outranks the chains
    got = gev._tldr_direction_read(rec)
    assert got["v"] is True and got["src"] == "state_board.row_states[].side"
    rec["state_board"]["counters"].update({"BoardSidesFor": 4, "BoardSidesAgainst": 1})   # rung 1
    got = gev._tldr_direction_read(rec)
    assert got["v"] is False and got["src"].startswith("state_board.counters")
    rec["state_board"]["counters"].update({"BoardSidesFor": 2, "BoardSidesAgainst": 2})   # balanced
    assert gev._tldr_direction_read(rec)["v"] is None             # untestable, NEVER "agrees"


# -- 4. watch_cited: the citable handle, in the writer's prose, never the footer ------------------------------
def test_watch_cited_reads_the_citable_handle_in_the_writers_prose_and_never_the_footer():
    sb = {"watch_rows": [{"handle": 12}, {"handle": "N13"}],
          "coverage": {"watch_rows": 2, "watch_cited": 0, "watch_referenced": 2}}
    footer = "## Mechanism\nCorn watch.\n\n## Sources\n[N12] synthetic row\n[N13] synthetic row"
    uncited = _live("w0", answer=footer, structured={"tldr": "t", "mechanism": "Corn watch."},
                    trace={"state_board": sb})
    cited = _live("w1", answer=footer, structured={"tldr": "t", "mechanism": "Corn watch [N12]."},
                  trace={"state_board": sb})
    cen = gev.instrument_census(rows=[uncited, cited])
    assert [r["watch_cited"] for r in cen["rows"]] == [0, 1]      # the footer's [N12] is never a citation
    assert cen["census"]["watch_cited"]["denominator"] == 4       # citable watch rows, stated
    no_contract = _live("w2", answer=footer, structured={"tldr": "t", "mechanism": "Corn watch [N12]."},
                        trace={"state_board": {"coverage": {"watch_rows": 2, "watch_cited": 0}}})
    row = gev.instrument_census(rows=[no_contract])["rows"][0]
    assert row["watch_cited"] is None                              # ABSENT without the contract, never 0
    assert row["coverage.watch_cited [producer]"] == 0             # ...while the producer's 0 is kept apart


# -- 5. the register line: BOTH populations, per cell ---------------------------------------------------------
def test_the_register_line_reports_both_populations_in_each_cell():
    cen = gev.instrument_census(_banked_deck())
    cells = cen["register_cells"]
    assert set(cells) == {"mandate-dark", "mandate-lit"}
    assert cells["mandate-dark"]["desk_register_hits"] > 0          # instrument words the leak list cannot see
    rep = "\n".join(gev.instrument_report(cen))
    for cell in ("mandate-dark", "mandate-lit"):
        line = next(x for x in rep.splitlines() if x.startswith(f"- register, {cell} cell"))
        assert "register_leaks:" in line and "desk_register_hits:" in line
        assert line.count("(population:") == 2 and line.count("n=") == 2


def test_a_page_with_zero_register_leaks_still_reports_its_desk_register_hits():
    body = "## Mechanism\nThe board reads the corn stocks row high [N1]."
    row = _live("d0", answer=body, structured={"tldr": "t", "mechanism": body})
    rec = gev._per_answer_record(row, "single")
    assert rec["register_leaks"] == 0
    got = gev.instrument_census([rec], [row])["rows"][0]
    assert got["register_leaks"] == 0 and got["desk_register_hits"] == 2


# -- 6. the count check: nouns off the trace's own keys, every mismatch quoted -------------------------------
def test_a_count_beside_a_noun_the_trace_mints_is_checked_against_its_counters_and_quoted():
    sb = {"chain_counts": {"total": 513, "rendered": 3, "distinct_sequences": 100, "distinct_markets": 4},
          "analogs": [{"n_candidates": 159, "n_contracts": 4}]}
    prose = ("One hundred chains of cause reach four markets; eight chains are carried here. "
             "Of 159 past candidates, this one is nearest. The 2013 frost matters. Seven apples fell. "
             "Managed money sits at 241,501 contracts [N31], and the 2026-12 contract settled lower [N36].")
    got = gev._count_check(prose, gev._count_pool(sb))
    assert got["checked"] == 4                                    # chains x2, markets, candidates
    assert [(m["noun"], m["printed"]) for m in got["mismatches"]] == [("chain", 8)]
    assert got["mismatches"][0]["quote"] == "eight chains are carried here"
    assert got["mismatches"][0]["trace_values"] == [3, 4, 100, 513]
    # a handle-bound clause is a SERVED ROW's figure (the verifier's), never a board count: MEASURED on the ten
    # unseen 09-23 pages, 9 of 38 attachments were "241,501 contracts [N31]" read against `n_contracts`
    assert gev._count_check("Managed money sits at 241,501 contracts [N31].", gev._count_pool(sb))["checked"] == 0
    # a signed number, a date and a range are not counts, handle or no handle
    assert gev._count_check("the 2026-12 contract, -3 contracts and 2-3 contracts", gev._count_pool(sb)) == \
        {"checked": 0, "mismatches": []}


def test_the_count_vocabulary_moves_with_the_trace_keys_and_is_never_a_typed_list():
    prose = "The shock reaches four markets and six venues."
    sb = {"chain_counts": {"distinct_markets": 4}}
    assert gev._count_check(prose, gev._count_pool(sb))["checked"] == 1        # venues: no key names it
    renamed = {"chain_counts": {"distinct_venues": 5}}
    got = gev._count_check(prose, gev._count_pool(renamed))
    assert [(m["noun"], m["printed"]) for m in got["mismatches"]] == [("venue", 6)]
    served = {"served_counts": [{"noun": "like states", "value": 3}]}           # CONTRACT C-I6
    got = gev._count_check("Nine like states sat this far out.", gev._count_pool(served))
    assert got["checked"] == 1 and got["mismatches"][0]["trace_values"] == [3]


# -- 7. THE DECK-LEVEL PINS: varied pages read varied values; constant ones are named VACUOUS ----------------
_REBASED = ("n_sections", "intent_ok", "tldr_direction", "watch_cited", "register_leaks",
            "desk_register_hits", "count_mismatches")
_CONSTANT_PRODUCERS = ("tldr_direction.agree [producer]", "coverage.watch_cited [producer]",
                       "coverage.events_referenced [producer]")


def test_a_varied_banked_deck_reads_varied_values_on_every_rebased_instrument():
    cen = gev.instrument_census(_banked_deck())
    assert cen["pages"] == 6
    for name in _REBASED:
        c = cen["census"][name]
        assert c["n"] >= gev._VACUITY_MIN_N, (name, c)
        assert c["distinct"] > 1 and c["vacuous"] is False, (name, c)
    assert cen["census"]["coverage.watch_referenced [producer]"]["vacuous"] is False


def test_an_instrument_that_reads_one_value_on_every_page_is_named_vacuous_and_never_quoted():
    cen = gev.instrument_census(_banked_deck())
    for name in _CONSTANT_PRODUCERS:
        assert cen["census"][name]["vacuous"] is True, name
        assert name in cen["vacuous"], name
    rep = gev.instrument_report(cen)
    vline = next(x for x in rep if "vacuous instruments" in x)
    for name in _CONSTANT_PRODUCERS:
        assert name in vline, name
        line = next(x for x in rep if x.startswith(f"- {name}:"))
        assert "NOT QUOTED -- VACUOUS" in line, line
    assert set(cen["vacuous"]) == set(_CONSTANT_PRODUCERS)          # exactly the constant ones, no re-based one
    assert vline.rsplit("): ", 1)[1].split(", ") == cen["vacuous"]


def test_a_deck_whose_producer_fields_are_absent_reads_ABSENT_never_zero_or_false():
    cen = gev.instrument_census(_absent_deck())
    for name, c in cen["census"].items():
        assert c["n"] == 0 and c["value"] is None and c["vacuous"] is None, (name, c)
    assert all(v is None for row in cen["rows"] for k, v in row.items() if k != "id")
    rep = gev.instrument_report(cen)
    for name, _k, _p in gev._INSTRUMENTS:
        line = next(x for x in rep if x.startswith(f"- {name}:"))
        assert "ABSENT on every page" in line and "n=0)" in line, line


def test_every_instrument_line_states_its_population_and_its_denominator():
    rep = gev.instrument_report(gev.instrument_census(_banked_deck()))
    names = [n for n, _k, _p in gev._INSTRUMENTS]
    lines = [x for x in rep if any(x.startswith(f"- {n}:") for n in names)]
    assert len(lines) == len(names)
    for x in lines:
        assert re.search(r"\(population: .+, n=\d+\)", x), x


# -- 8. the artifact: ONE appended key, the per-answer columns untouched --------------------------------------
def test_the_baseline_json_appends_the_census_after_per_answer_and_the_record_keeps_its_columns():
    rows = [_live(f"b{i}", answer="## Mechanism\nx [N1].\n\n## Sources\n[N1]",
                  structured={"tldr": "t", "mechanism": "x [N1]."}) for i in range(2)]
    doc = gev._baseline_json(rows, run_kind="single", model="m", judged=False, eval_set="s",
                             graph_version="g", corpus_fp="c")
    assert list(doc)[-2:] == ["per_answer", "instruments"]          # APPENDED, never interleaved
    assert doc["instruments"]["census"]["n_sections"]["n"] == 2
    rec = doc["per_answer"][0]
    assert "instruments" not in rec and list(rec)[-1] == "bare_handle_escapes"   # the tail pin holds
    assert list(rec) == list(gev._per_answer_record(rows[1], "single"))


def test_the_report_carries_the_instrument_panel_before_the_per_row_answers():
    rows = [_live("r0", answer="## Mechanism\nx.", structured={"tldr": "t", "mechanism": "x."},
                  kind_history=["plan:None->reasoning", "family_facet:reasoning->hybrid"]),     # promoted: True
            _live("r1", answer="## Mechanism\nx.", structured={"tldr": "t", "mechanism": "x."},
                  intent="reasoning", expected="hybrid", kind_history=["plan:None->reasoning"])]  # a real miss
    rep = gev.report(rows, model="m")
    assert "## Instrument readings" in rep
    assert rep.index("## Instrument readings") < rep.index("## r0")
    # the routing lines state the population they scored: rows whose router emitted a route (n=2 here)
    head = next(x for x in rep.splitlines() if x.startswith("- **intent routed correctly: "))
    assert head.startswith("- **intent routed correctly: 1/2**") and "population:" in head and head.endswith("n=2)")
    panel = next(x for x in rep.splitlines() if x.startswith("- **intent routed correctly**: "))
    assert panel.startswith("- **intent routed correctly**: **1/2**") and panel.endswith("n=2)")
    assert "- intent_ok: 1 of 2 true (population:" in rep          # the header, the panel, the census: ONE read


def test_a_vocabulary_mismatch_leaves_the_routing_panels_denominator_and_is_named_there():
    rows = [_live(f"v{i}", kind_history=["plan:None->hybrid"]) for i in range(3)]
    rr = "\n".join(gev.routing_report(rows))
    assert "**intent routed correctly**: **0/0**" in rr and "n=0)" in rr        # NOT 0/3 routed wrong
    assert "intent VOCABULARY MISMATCH on 3 row(s)" in rr and "['reasoning']" in rr
    assert "- **intent routed correctly: " not in gev.report(rows, model="m")  # no scorable row, no header


def test_the_cli_rereads_a_banked_baseline_at_zero_cost(tmp_path, monkeypatch, capsys):
    p = tmp_path / "baseline_synthetic.json"
    p.write_text(json.dumps({"per_answer": _banked_deck()}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["eval", "--instruments-from", str(p)])
    assert gev.main() == 0
    out = capsys.readouterr().out
    assert "vacuous instruments" in out and "tldr_direction.agree [producer]" in out
