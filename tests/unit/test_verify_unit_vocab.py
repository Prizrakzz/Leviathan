"""D-DA UNIT-VOCABULARY GATE (2026-09-06) -- rule (g)'s stated residual, caught at the charge site.

THE RESIDUAL THIS FILE CLOSES, in the words the rule-(g) note used to hold it open with: rule (g) is
STRUCTURAL ("this numeral is a label's scale"), so a MIS-TRANSCRIBED scale was caught by nothing --
"US corn feed use is 154,947 (9999 MT)" exempted 9999 exactly as it exempts 1000, `quote_mismatch` reads
QUOTED spans only, and the footer lane reads the engine's own unit column, never the model's prose. The
same hole covered a bare second figure standing before a unit word ("5900 9999 MT").

THE CATCHER IS A POST-FILTER AT THE CHARGE SITE, never a change to the extractor (`_claim_number_spans`
is a pure function of the sentence and its signature is frozen by the cycle-8 termination branch): the
exempted scale must be a numeral one of the sentence's OWN served rows prints in its unit string, and
`_check_number_handle` re-admits it as a claim when no such row does.

The pins are in four bands:
  * THE CATCH -- the mis-transcribed scale and the bare second figure are charged, proportionately;
  * THE EXEMPT -- every rendered label its own row declares still costs nothing, so the measured
    33-of-35 `number_unbacked` false-positive class stays closed;
  * THE FENCES -- the stand-downs (a served call that records no unit; one that records a unit on only
    SOME of its rows; one whose unit string carries no numeral and so declares no scale), the errored
    call that is skipped rather than standing the gate down, the grouped member that contributes
    vocabulary, the one-sided feed (guard only, never the mismatch pool), and the two rollbacks;
  * THE REPLAY -- the banked control arm, by_rule unmoved (3 / 6 / 41).

Each stand-down pin carries a DISCRIMINATING assertion: it is written so that widening the fence by one
word (`all` -> `any`, `_UL_VOCAB_NUM.search(u)` -> `u`) turns it red, because a fence nothing can falsify
is a comment, not a pin.
"""
from __future__ import annotations

import copy
import io
import json
import re
from collections import Counter
from pathlib import Path

import pytest
from leviathan.graphrag import verify as vf

_ARTIFACT = (Path(__file__).resolve().parents[2] / "data" / "batch_runs"
             / "da_baseline_control_20260904T141206Z.json")

# The served row of the measured class: the label it PRINTS is "(1000 MT)" while the row's VALUE is the
# bare figure. The whole gate is the difference between a prose scale this row declares and one it does not.
_PSD = {"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption",
                  "commodity": "corn"},
        "rows": [{"value": "154947", "unit": "(1000 MT)", "knowledge_date": "2026-08-12"}]}


def _run(tldr, calls):
    """verify_citations on a one-sentence draft; returns (report, the surviving prose)."""
    s = {"tldr": tldr, "mechanism": "", "sources": []}
    rep = vf.verify_citations(s, [], copy.deepcopy(calls))
    return rep, s["tldr"]


# -- BAND 1: THE CATCH ---------------------------------------------------------------------------------

def test_the_mis_transcribed_scale_is_charged():
    """THE PIN. The row prints "(1000 MT)"; the prose writes "(9999 MT)". 9999 is a scale no served row
    of this sentence declares, so it comes back as a claim, matches no served value, and is charged."""
    assert vf._unit_label_scale_values("US corn feed use is 154,947 (9999 MT)") == [9999.0]
    assert vf._unit_vocab_claims("US corn feed use is 154,947 (9999 MT) [N1].", [_PSD]) == [9999.0]
    rep, prose = _run("US corn feed use is 154,947 (9999 MT) [N1].", [_PSD])
    assert rep["by_rule"].get("number_unbacked", 0) == 1 and rep["stripped"] == 1
    assert "[N1]" not in prose


def test_the_remedy_is_the_proportionate_one():
    """`number_unbacked` strips the mis-citing HANDLE and leaves the sentence standing -- which is why
    the gate feeds that guard and not the fail-closed `number_mismatch` that deletes a sentence whole."""
    _rep, prose = _run("US corn feed use is 154,947 (9999 MT) [N1].", [_PSD])
    assert "US corn feed use is 154,947 (9999 MT)" in prose


def test_a_bare_second_figure_before_a_unit_word_is_charged():
    """The second shape the residual covered: "5900 9999 MT" is the same structure as the legitimate
    "-83.476 1000 MT" and only the rows can tell them apart. The row prints "(1000 MT)", so 9999 is not
    a scale this sentence's rows know and it is charged; the figure 5900 IS served and is not."""
    calls = [{"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
              "rows": [{"value": "5900", "unit": "(1000 MT)"}]}]
    assert vf._unit_label_scale_values("The pace ran 5900 9999 MT") == [9999.0]
    rep, prose = _run("The pace ran 5900 9999 MT on the window [N1].", calls)
    assert rep["by_rule"].get("number_unbacked", 0) == 1 and rep["stripped"] == 1
    assert "[N1]" not in prose and "5900 9999 MT" in prose


def test_the_second_scale_token_of_a_consumed_label_is_checked_too():
    """A label carries at most two scales ("1000 60 KG BAGS"); the sub-unit weight is part of the label,
    so the vocabulary has to see it. A row that prints "(1000 MT)" declares 1000 and NOT 60."""
    assert vf._unit_label_scale_values("arabica production 42,300 (1000 60 KG BAGS)") == [1000.0, 60.0]
    calls = [{"query": {"table": "silver_psd_attributes", "metric": "Production"},
              "rows": [{"value": "42300", "unit": "(1000 MT)"}]}]
    assert vf._unit_vocab_claims("arabica production 42,300 (1000 60 KG BAGS) [N1].", calls) == [60.0]
    rep, _prose = _run("arabica production 42,300 (1000 60 KG BAGS) [N1].", calls)
    assert rep["by_rule"].get("number_unbacked", 0) == 1


# -- BAND 2: THE EXEMPT -- the 33-of-35 class stays closed ---------------------------------------------

def test_the_measured_sentence_still_takes_zero_strips():
    """The defect rule (g) exists for, re-run through the gate: the label the row PRINTS costs nothing."""
    n22 = {"query": _PSD["query"], "rows": [{"value": "161297", "unit": "(1000 MT)"}]}
    sent = ("US corn feed use is 154,947 (1000 MT) for MY2026 against 161,297 (1000 MT) "
            "for MY2025 [N1][N2].")
    assert vf._unit_vocab_claims(sent, [_PSD, n22]) == []
    rep, prose = _run(sent, [_PSD, n22])
    assert rep["stripped"] == 0 and "[N1]" in prose and "[N2]" in prose


def test_every_rendered_label_shape_its_own_row_declares_is_still_exempt():
    """The enumerated corpus of labels that carry a numeral (registry + the PSD long table's verbatim
    `unit_desc`), each paired with the ROW that prints it. Nothing here may cost a strip."""
    cases = [
        ("area harvested 35,700 (1000 HA) [N1].", "35700", "(1000 HA)"),
        ("the fresh-citrus read is 12,345 1000 boxes on the window [N1].", "12345", "1000 boxes"),
        ("arabica 1,234 1000 60-kg bags [N1].", "1234", "1000 60 KG BAGS"),
        ("carcass output 1,200 (1000 MT CWE) [N1].", "1200", "(1000 MT CWE)"),
        ("the herd is 1,917 (1000 HEAD) [N1].", "1917", "(1000 HEAD)"),
        ("arabica production 42,300 (1000 60 KG BAGS) [N1].", "42300", "(1000 60 KG BAGS)"),
        ("cotton use 7,777 1000 480 lb. Bales [N1].", "7777", "1000 480 lb. Bales"),
        ("coffee stocks of 12,345 60-kg bags [N1].", "12345", "60-kg bags"),
        ("the inside quote is 2,450,000 COP per 125-kg carga [N1].", "2450000",
         "COP per 125-kg carga"),
        ("world output 26.5 MMT (cotton: million 480-lb bales) [N1].", "26.5",
         "MMT (cotton: million 480-lb bales)"),
        ("weekly meal export pace changed by -83.476 1000 MT [N1].", "-83.476", "1000 MT"),
    ]
    for prose, value, unit in cases:
        calls = [{"query": {"table": "silver_psd_attributes", "metric": "Production"},
                  "rows": [{"value": value, "unit": unit}]}]
        assert vf._unit_vocab_claims(prose, calls) == [], prose
        rep, out = _run(prose, calls)
        assert rep["stripped"] == 0 and "[N1]" in out, prose


def test_a_bare_thousand_in_prose_is_still_the_extractors_own_claim():
    """The gate adds nothing here: "about 1000 tonnes" has no accepted figure in front of it, so rule (g)
    never exempted it and it was a claim all along. The gate must not double-count it."""
    assert vf._unit_label_scale_values("the cargo was about 1000 tonnes") == []
    assert vf._unit_vocab_claims("The cargo was about 1000 tonnes [N1].", [_PSD]) == []


# -- BAND 3: THE FENCES --------------------------------------------------------------------------------

def test_a_served_call_that_records_no_unit_stands_the_gate_down():
    """THE DOCKETED LIMIT, pinned: "this row prints no scale" and "this row's scale was never recorded"
    are different facts, and only the first may charge. A call whose rows carry no `unit` leaves the
    sentence with the structural verdict -- which is also what keeps this gate off the registry."""
    calls = [{"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption"},
              "rows": [{"value": "154947"}]}]
    assert vf._served_unit_vocab("US corn feed use is 154,947 (9999 MT) [N1].", calls) is None
    rep, prose = _run("US corn feed use is 154,947 (9999 MT) [N1].", calls)
    assert rep["stripped"] == 0 and "[N1]" in prose


def test_an_empty_or_errored_call_is_skipped_and_never_stands_the_gate_down():
    """A call that served no row (`rows: []`, the artifact's `status: error` shape) states nothing about
    units. It must not be read as "vocabulary unknown", or one errored lookup would disarm the gate for
    every sentence that cites it beside a good row."""
    err = {"query": {"table": "silver_psd", "metric": "production_mt"}, "rows": []}
    assert vf._served_unit_vocab("x [N1] [N2]", [err, _PSD]) == {1000}
    rep, prose = _run("US corn feed use is 154,947 (9999 MT) [N1] [N2].", [err, _PSD])
    # EXACT, not ">= 1": a gate charge is a SENTENCE verdict, so BOTH handles in the sentence take it --
    # HEAD's own accounting for any sentence-level unbacked magnitude, and the reason the note's
    # "the mis-citing HANDLE goes" must not be read as "exactly one handle goes".
    assert rep["by_rule"] == {"number_unbacked": 2} and rep["stripped"] == 2
    assert "[N1]" not in prose and "[N2]" not in prose


def test_a_two_handle_sentence_is_charged_once_per_handle():
    """The same accounting where both handles resolve to real rows: one bad scale, two dead handles, and
    the prose still standing. Pinned because "the mis-citing HANDLE goes" reads singular."""
    n2 = {"query": {"table": "silver_psd_attributes", "metric": "Exports"},
          "rows": [{"value": "161297", "unit": "(1000 MT)"}]}
    sent = "US corn feed use is 154,947 (9999 MT) and exports 161,297 [N1][N2]."
    rep, prose = _run(sent, [_PSD, n2])
    assert rep["by_rule"] == {"number_unbacked": 2} and rep["stripped"] == 2
    assert prose == "US corn feed use is 154,947 (9999 MT) and exports 161,297."


def test_a_sentence_citing_no_in_range_number_handle_is_never_gate_charged():
    """No served rows, no vocabulary, no charge -- the [E]-only and out-of-range shapes."""
    assert vf._served_unit_vocab("US corn feed use is 154,947 (9999 MT) [E4].", [_PSD]) is None
    assert vf._served_unit_vocab("US corn feed use is 154,947 (9999 MT) [N9].", [_PSD]) is None
    assert vf._unit_vocab_claims("US corn feed use is 154,947 (9999 MT) [E4].", [_PSD]) == []


def test_a_grouped_handles_members_contribute_their_vocabulary():
    """CYCLE-9 amendment 3a's reading, and admissible for the same reason: a grouped citation's row was
    served to the reader exactly like a solitary one, and a wider vocabulary can only ever REMOVE a
    charge. The discriminating half is the second assertion -- strip N3's unit and 60 is charged."""
    n3 = {"query": {"table": "silver_psd_attributes", "metric": "Production"},
          "rows": [{"value": "42300", "unit": "1000 60 KG BAGS"}]}
    n1 = {"query": {"table": "silver_psd_attributes", "metric": "Production"},
          "rows": [{"value": "42300", "unit": "(1000 MT)"}]}
    sent = "arabica production 42,300 (1000 60 KG BAGS) [N1] [N2, N3]."
    assert vf._served_unit_vocab(sent, [n1, n1, n3]) == {1000, 60}
    rep, _prose = _run(sent, [n1, n1, n3])
    assert rep["stripped"] == 0
    # The discriminator needs a label that DECLARES a scale and simply not this one -- "(1000 MT)" gives
    # the sentence the vocabulary {1000}, so the 60 is charged. (A numeral-free unit would instead stand
    # the whole gate down; that is the next pin, and using it here would have made this one vacuous.)
    thou = {"query": n3["query"], "rows": [{"value": "42300", "unit": "(1000 MT)"}]}
    assert vf._unit_vocab_claims(sent, [n1, n1, thou]) == [60.0]


def test_a_call_that_records_a_unit_on_only_some_of_its_rows_stands_the_gate_down():
    """THE STAND-DOWN IS ROW-GRANULAR, AND THE RENDERER IS WHY (review MAJOR, 2026-09-06). A per-CALL
    `any(units)` test would build the vocabulary out of the unit-bearing rows alone and then charge the
    model for copying the label the citation printed for the row beside them: `citations.from_number`
    renders `unit = r.get("unit") or _metric_unit(table, metric, commodity)`, and the registry's
    `_metric_unit("silver_psd_attributes", "Feed Dom. Consumption", "corn")` is "1000 MT" -- so the
    reader of this very call was shown "154947 1000 MT" for the row that recorded no unit at all.
    83 of 4074 served calls in the banked corpus are mixed this way (2.0%), and 1 of the 46
    label-bearing sentences already cites one.
    THE FIRST HALF IS THE MEASURED FIXTURE (a numeral-free neighbour); THE SECOND IS THE DISCRIMINATING
    ONE. Only the second turns red on `all` -> `any`, because the numeral-free stand-down below already
    covers the first on its own -- so a neighbour that DOES declare a scale is what actually holds this
    fence: the sentence's own cited row was rendered "154947 1000 MT" from the registry, the neighbour
    declares 60, and `any` would charge the reader for the label the citation printed."""
    mixed = [{"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption",
                        "commodity": "corn"},
              "rows": [{"value": "8.85", "unit": "Million Bushels"}, {"value": "154947"}]}]
    sent = "US corn feed use is 154947 (1000 MT) [N1]."
    assert vf._served_unit_vocab(sent, mixed) is None
    assert vf._unit_vocab_claims(sent, mixed) == []
    rep, prose = _run(sent, mixed)
    assert rep["by_rule"] == {} and rep["stripped"] == 0 and "[N1]" in prose

    scaled_neighbour = [{"query": mixed[0]["query"],
                         "rows": [{"value": "8.85", "unit": "60-kg bags"}, {"value": "154947"}]}]
    assert vf._served_unit_vocab(sent, scaled_neighbour) is None          # NOT {60}
    rep2, prose2 = _run(sent, scaled_neighbour)
    assert rep2["by_rule"] == {} and rep2["stripped"] == 0 and "[N1]" in prose2


def test_a_unit_string_with_no_numeral_in_it_states_no_scale_and_stands_the_gate_down():
    """"THIS ROW PRINTS NO SCALE" IS NOT "THIS METRIC HAS NO SCALE" (review MINOR-1, 2026-09-06). A row
    printing the bare "MMT" declares a unit, but no scale vocabulary -- and the registry itself declares
    "MMT (cotton: million 480-lb bales)" for the metrics those rows belong to, so a model writing the
    full label would be charged for the 480 the short string never had room for. Numeral-free units are
    2,281 of 2,515 unit-bearing row prints in the banked corpus (90.7%, 28 of 30 distinct strings), so
    the fail-closed reading would have put the gate's largest surface on the wrong side of its own
    "may only ever ADD a charge" promise.
    THE DISCRIMINATING HALF is the second row: give the same call a numeral-bearing label and the gate
    comes back to life on the identical prose."""
    mmt = [{"query": {"table": "silver_psd_attributes", "metric": "Production", "commodity": "cotton"},
            "rows": [{"value": "26.5", "unit": "MMT"}]}]
    sent = "world output 26.5 MMT (cotton: million 480-lb bales) [N1]."
    assert vf._unit_label_scale_values(vf._HANDLE.sub("", sent)) == [480.0]   # rule (g) DID exempt it
    assert vf._served_unit_vocab(sent, mmt) is None
    rep, prose = _run(sent, mmt)
    assert rep["by_rule"] == {} and rep["stripped"] == 0 and "[N1]" in prose
    scaled = [{"query": mmt[0]["query"],
               "rows": [{"value": "26.5", "unit": "1000 MT"}]}]
    assert vf._unit_vocab_claims(sent, scaled) == [480.0]
    assert _run(sent, scaled)[0]["by_rule"] == {"number_unbacked": 1}


def test_a_comma_formatted_unit_declares_its_thousands_scale():
    """A row printing "1,000 MT" declares 1000, not {0, 1} (review MINOR-4). Rule (g) fences the comma on
    the PROSE side -- an exempted scale is a BARE digit run (MAJOR-1) -- and fencing it on the VOCABULARY
    side too would charge the prose that copied the row's own label in the form the extractor demands.
    No unit in the banked corpus carries a comma today (0 of 30 distinct strings), so this pins a shape
    the estate has not printed yet rather than repairing a live miss."""
    comma = [{"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption"},
              "rows": [{"value": "154947", "unit": "1,000 MT"}]}]
    assert vf._served_unit_vocab("x [N1]", comma) == {1000}
    sent = "US corn feed use is 154,947 (1000 MT) [N1]."
    assert vf._unit_vocab_claims(sent, comma) == []
    rep, prose = _run(sent, comma)
    assert rep["stripped"] == 0 and "[N1]" in prose
    # and the fence still points the right way: a scale this comma-formatted label does NOT declare
    assert vf._unit_vocab_claims("US corn feed use is 154,947 (9999 MT) [N1].", comma) == [9999.0]


def test_the_gate_may_only_add_a_charge_and_never_rescue_a_mismatch():
    """THE ONE-SIDEDNESS, pinned where it is decided: the re-admitted token joins the `number_unbacked`
    guard and NOT the `number_mismatch` pool. `_num_matches` is an ANY-of predicate, so feeding it 9999
    -- which here coincides with the served row's value -- would have counted as the sentence's one
    match and rescued a fabricated 42.5. The sentence dies as number_mismatch, as it must."""
    calls = [{"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
              "rows": [{"value": "9999", "unit": "1000 MT"}]}]
    sent = "The pace was 42.5 (9999 MT) on the window [N1]."
    assert vf._unit_vocab_claims(sent, calls) == [9999.0]          # the gate DID re-admit it ...
    rep, prose = _run(sent, calls)
    assert rep["by_rule"] == {"number_mismatch": 1}                 # ... and the mismatch still fired
    assert "42.5" not in prose


def test_the_rollback_flag_restores_the_pre_gate_charge(monkeypatch):
    """GRAPHRAG_VERIFY_UNIT_VOCAB=off -- the shape `GRAPHRAG_VERIFY_NUM_POOL` / `..._NUM_MODE` already
    have in this module. Off is HEAD's verdict on the residual, byte for byte."""
    monkeypatch.setenv("GRAPHRAG_VERIFY_UNIT_VOCAB", "off")
    assert vf._unit_vocab_claims("US corn feed use is 154,947 (9999 MT) [N1].", [_PSD]) == []
    rep, prose = _run("US corn feed use is 154,947 (9999 MT) [N1].", [_PSD])
    assert rep["stripped"] == 0 and "[N1]" in prose


def test_the_cascade_quant_rollback_takes_the_gate_with_it(monkeypatch):
    """GRAPHRAG_CASCADE_QUANT=off reverts the whole quant guard, and the gate feeds that guard -- so it
    must revert too, at the GATE and not at the charge site alone. `_check_number_handle` already sits
    inside the quant branch, but the `strip_audit` call does not: before this fence, quant-off left the
    audit listing a re-admitted 9999 that no charge could have used (review MINOR-3). The audit list is
    HEAD's again here, byte for byte."""
    monkeypatch.setenv("GRAPHRAG_CASCADE_QUANT", "off")
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    mis = [{"query": {"table": "silver_esr", "metric": "weekly_exports_1000mt"},
            "rows": [{"value": "9999", "unit": "1000 MT"}]}]
    sent = "The pace was 42.5 (9999 MT) on the window [N1]."
    assert vf._unit_vocab_claims(sent, mis) == []
    rep, _prose = _run(sent, mis)
    assert [r["numbers"] for r in rep["strip_audit"]] == [[42.5]]


def test_the_label_scans_early_out_is_an_identity_and_not_an_approximation():
    """`_unit_label_scale_values` returns before it pays for the extractor on a sentence that holds no
    digit-then-unit-word shape at all. That is sound by construction -- rule (g) can only exempt a scale
    `_UL_TAIL` matches, and `_UL_TAIL` is anchored at the end of a bare digit run, which is exactly the
    leading digit `_UL_ANY` adds -- and together with the reorder below it is what pays the gate's cost
    back (extractor runs per control arm: HEAD 406, the naive gate 603, this one 411 -- deterministic,
    where wall clock on a shared box is not). The pin is the two directions of the soundness claim: the
    shortcut never fires on a sentence that HAS a label, and it does fire on prose with no unit word."""
    for prose in ("US corn feed use is 154,947 (9999 MT)", "The pace ran 5900 9999 MT",
                  "arabica production 42,300 (1000 60 KG BAGS)", "cotton use 7,777 1000 480 lb. Bales",
                  "coffee stocks of 12,345 60-kg bags", "area harvested 35,700 (1000 HA)",
                  "the inside quote is 2,450,000 COP per 125-kg carga",
                  "world output 26.5 MMT (cotton: million 480-lb bales)"):
        assert vf._unit_label_scale_values(prose), prose
        assert vf._UL_ANY.search(prose), prose
    for prose in ("the cargo was about 1000 tonnes", "prices rose 12.5 percent in 2024",
                  "the balance was 154,947 on the week", ""):
        assert vf._UL_ANY.search(prose) is None, prose
        assert vf._unit_label_scale_values(prose) == [], prose


def test_the_cheap_vocabulary_question_is_asked_before_the_expensive_label_scan(monkeypatch):
    """THE REORDER, pinned deterministically. `_served_unit_vocab` reads dicts; `_unit_label_scale_values`
    runs the claim extractor -- and most sentences stand the gate down, so asking the cheap question
    first is what keeps the gate off the verifier's hot path. If the label scan is ever reached on a
    stand-down sentence again, this goes red rather than merely getting slower."""
    def _never(*_a, **_k):
        raise AssertionError("the label scan was reached on a stand-down sentence")
    monkeypatch.setattr(vf, "_unit_label_scale_values", _never)
    no_unit = [{"query": {"table": "silver_psd_attributes", "metric": "Feed Dom. Consumption"},
                "rows": [{"value": "154947"}]}]
    assert vf._unit_vocab_claims("US corn feed use is 154,947 (9999 MT) [N1].", no_unit) == []
    assert vf._unit_vocab_claims("US corn feed use is 154,947 (9999 MT) [E4].", [_PSD]) == []


def test_the_extractor_itself_did_not_move():
    """The gate is a POST-FILTER: rule (g) still exempts the mis-transcribed scale, `cycle8=False` still
    returns HEAD's (a)-(d) view, and the frozen signature is untouched."""
    assert vf._claim_numbers_in("US corn feed use is 154,947 (9999 MT)") == [154947.0]
    assert vf._claim_numbers_in("The pace ran 5900 9999 MT") == [5900.0]
    off = [v for _a, _b, v in vf._claim_number_spans("feed use at 154,947 (9999 MT)", cycle8=False)]
    assert off == [154947.0, 9999.0]


def test_the_strip_audit_numbers_list_carries_the_re_admitted_scale(monkeypatch):
    """The audit list's own promise -- "the offending magnitudes are the sentence's CLAIM numbers" -- has
    to survive the gate, or an RCA dump would show a strip with no number to blame it on."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    rep, _prose = _run("US corn feed use is 154,947 (9999 MT) [N1].", [_PSD])
    rows = [r for r in rep["strip_audit"] if r["rule"] == "number_unbacked"]
    assert len(rows) == 1 and rows[0]["numbers"] == [154947.0, 9999.0]


# -- BAND 4: THE REPLAY -- the banked control arm ------------------------------------------------------

def test_the_control_arm_replay_is_unmoved_by_the_gate():
    """The arm rule (g) was measured on, replayed end to end through `verify_citations` (the artifact is
    gitignored, so this pin is skipped in a clean clone). The gate must not re-open the 33-of-35 class:
    number_unbacked 3, number_mismatch 6, undeclared_unsupported 41 -- and the census that explains why
    (17 rule-(g) scale tokens across 10 sentences, 4 printed by a served row of their own sentence, 13
    standing the gate down because the cited call recorded no unit or recorded one with no numeral in
    it, 0 re-admitted). THE GATE'S HONEST REACH ON TODAY'S CORPUS IS 4 OF 17, and that is the stated
    price of the two fail-open fences above, not a miss to be quietly widened."""
    if not _ARTIFACT.exists():
        pytest.skip("da_baseline_control artifact is gitignored and absent from this tree")
    doc = json.load(io.open(_ARTIFACT, encoding="utf-8"))
    by_rule, stripped = Counter(), 0
    for a in doc["per_answer"]:
        rd = a.get("raw_draft") or {}
        st = {"tldr": rd.get("preverify_tldr") or "",
              "mechanism": rd.get("preverify_mechanism") or "", "sources": []}
        rep = vf.verify_citations(st, [], copy.deepcopy(a.get("served_rows") or []))
        by_rule.update(rep.get("by_rule") or {})
        stripped += rep.get("stripped", 0)
    assert dict(by_rule) == {"undeclared_unsupported": 41, "number_unbacked": 3, "number_mismatch": 6}
    assert stripped == 50

    exempted = printed = stand_down = readmitted = 0
    bound = re.compile(r"[.!?;](?=\s|$)|\n")
    for a in doc["per_answer"]:
        rd, calls = (a.get("raw_draft") or {}), (a.get("served_rows") or [])
        for field in ("preverify_tldr", "preverify_mechanism"):
            text, at = rd.get(field) or "", 0
            for b in list(bound.finditer(text)) + [None]:
                end = b.end() if b is not None else len(text)
                if end <= at:
                    continue
                sent, at = text[at:end], end
                scales = vf._unit_label_scale_values(vf._HANDLE.sub("", sent))
                if not scales:
                    continue
                exempted += len(scales)
                vocab = vf._served_unit_vocab(sent, calls)
                if vocab is None:
                    stand_down += len(scales)
                    continue
                printed += sum(1 for v in scales if int(v) in vocab)
                readmitted += sum(1 for v in scales if int(v) not in vocab)
    assert (exempted, printed, stand_down, readmitted) == (17, 4, 13, 0)
