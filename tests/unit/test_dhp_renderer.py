"""D-HP H1 -- THE RENDERER + VERIFIER HALF: the slot resolver, the digit-lint, the two binding refusals.

WHAT THIS FILE OWNS (the conformance suite test_dhp_handle_grammar.py owns the GRAMMAR's twelve-consumer
table; this owns what the renderer DOES with a parsed token):
  D-HP-11  the [N] default flip, the SIGN clause, `grouped_in_slot`, and the cycle-10 reconciliation
  D-HP-11/12  the `[N1b]` TRAP -- suffix-aware member resolution that REFUSES rather than guesses
  D-HP-12  the digit-lint: verify's charge, the R3(b) [E]-cited exemption, and the render-time remedy
  D-HP-13  direction-vs-sign, its POLARITY TABLE and its four refusals
  D-HP-14  the period scope check and the `wrong_slot_audit` column
  D-HP-10  the [E] resolution pass and the `prose_handles` census
  D-HP-9   verify's positional [E] branch (the half that lives in verify.py), and its pinned CONSEQUENCE

THE ONE RULE EVERY TEST HERE ALSO ASSERTS, ONE WAY OR ANOTHER: with `handle_prose=False` the render half
is the pre-D-HP renderer, byte for byte. That is the control arm, and it is what makes G1 a comparison.
"""
from __future__ import annotations

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import verify as vf


def _call(metric: str, value, unit: str = "MMT", commodity: str = "palm_oil",
          period: str | None = None, table: str = "silver_mpob") -> dict:
    """One numbers-agent call record, in the shape `cit.from_number` reads."""
    q = {"table": table, "metric": metric, "commodity": commodity}
    if period:
        q["period"] = period
    return {"query": q, "rows": [{"value": value, "unit": unit}], "status": "ok", "shown": [value]}


def _st(tldr: str, mechanism: str = "") -> dict:
    return {"tldr": tldr, "mechanism": mechanism}


# ══ D-HP-11/12 -- THE `[N1b]` TRAP ═══════════════════════════════════════════════════════════════════

def test_the_n1b_trap_is_defused_from_BOTH_sides_at_once():
    """H0 RECORDED THIS AS DEFECT 1 AND REFUSED TO FIX HALF OF IT (10.4): `_N_HANDLE_RX` carried no
    `[a-z]?`, so `[N1b]` was INERT DEBRIS that reached the reader as literal text -- but widening the
    regex ALONE would have resolved it onto call 1's HEADLINE row, "converting inert debris into a
    MIS-BINDING, which is the wave's #1 risk".

    BOTH SIDES SHIP HERE. The token is now SEEN (so it cannot reach the page) and the suffix TRAVELS with
    its index (so it cannot borrow the headline). The verdict is UNRESOLVABLE and the remedy is the
    shipped ladder -- D3, deletion beats a fourth fence."""
    calls = [_call("stocks", 1.62)]
    # (1) SEEN: the token no longer survives to the reader as literal text.
    st = _st("Stocks were at [N1b] last month.")
    census = an._resolve_number_handles(st, calls, handle_prose=True)
    assert "[N1b]" not in st["tldr"]
    assert census["unresolvable"] == 1 and census["sentences_dropped"] == 1
    # (2) NOT MIS-BOUND: call 1's headline value never reaches the page under the sibling's id.
    assert "1.62" not in st["tldr"]
    assert census["substituted"] == 0
    # (3) the refusal is the RESOLVER's, stated at the value producer itself.
    assert an._number_handle_value(calls[0], 1, "") == "1.62 MMT"
    assert an._number_handle_value(calls[0], 1, "b") is None


def test_a_suffixed_member_inside_a_group_is_narrowed_away_not_promoted():
    """THE SAME TRAP IN ITS GROUPED FORM, which is the shape that actually reaches a dense menu.
    `[N1, N1b]` cites TWO ROWS of ONE call. The headline resolves and the invented sibling does not, so
    the token is NARROWED to the survivor -- and the survivor is re-emitted through
    `_n_handle_token_pairs`, which keeps a real sibling's own id rather than silently promoting it."""
    st = _st("Stocks stood beside [N1, N1b] on the week.")
    census = an._resolve_number_handles(st, [_call("stocks", 1.62)], handle_prose=True)
    assert "[N1]" in st["tldr"] and "N1b" not in st["tldr"]
    assert census["handles_dropped"] == 1 and census["unresolvable"] == 1
    # the index VIEW still reports one index (every pre-D-HP caller asks an index question)
    assert an._n_handle_members("[N1, N1b]") == [1]
    assert an._n_handle_pairs("[N1, N1b]") == [(1, ""), (1, "b")]
    assert an._n_handle_token_pairs([(1, ""), (2, "c")]) == "[N1, N2c]"


def test_a_suffixed_range_endpoint_refuses_the_range_reading_instead_of_promoting_it():
    """H1 FIX Z8, THE RANGE BYPASS. The first build admitted `[a-z]?` on both endpoints and then expanded
    over INTEGERS, so `_n_handle_pairs("[N1b-N3]")` returned exactly what `[N1-N3]` returns -- `N1b`
    PROMOTED to call 1's headline through the ONE syntax that skips the pair producer, whose entire reason
    for existing is that no consumer may hold `1` without knowing it came from `N1b`.

    THE REFUSAL IS THE SAME REFUSAL A SCALAR GETS: the token drops to the MEMBER reading, the suffixed
    member carries its letter, and `_number_handle_value` declines it. Bounded either way (a range is
    never solitary, so it is never spliced), but the cost of the bypass was a citation rendered as
    `[N1, N2, N3]` for a row the model never addressed."""
    assert an._n_handle_pairs("[N1b-N3]") == [(1, "b"), (3, "")]
    assert an._n_handle_pairs("[N1b" + chr(0x2013) + "N4]") == [(1, "b"), (4, "")]
    assert an._n_handle_pairs("[N1-N3b]") == [(1, ""), (3, "b")]     # ...either endpoint
    assert an._n_handle_pairs("[N1-N3]") == [(1, ""), (2, ""), (3, "")]   # the clean range is unmoved
    assert an._n_handle_members("[N1-N6]") == [1, 2, 3, 4, 5, 6]      # unmoved
    assert an._number_handle_value(_call("stocks", 1.62), 1, "b") is None


# ══ D-HP-11 -- THE FLIP, THE SIGN CLAUSE, AND `grouped_in_slot` ══════════════════════════════════════

def test_the_slot_cue_becomes_a_confirmation_not_a_precondition():
    """D-HP-7's contract is "handle ONLY, written in the slot where the figure belongs", so the model
    wrote NO digit and a solitary RESOLVED handle IS the figure whether or not a value-introducing word
    precedes it. Under the shipped (control) rule a cue MISS leaves the token on the page -- which under
    handle-only prose is the D-PQ HANDLE-1 defect restored, the exact thing this pass exists to abolish.

    THE CONTROL ARM IS BYTE-IDENTICAL, which is the other half of the claim."""
    calls = [_call("stocks", 1.62)]
    off = _st("Stocks [N1] this month.")
    assert an._resolve_number_handles(off, calls) == {"substituted": 0, "handles_dropped": 0,
                                                      "sentences_dropped": 0, "unresolvable": 0}
    assert off["tldr"] == "Stocks [N1] this month."                  # no cue -> untouched, as shipped

    on = _st("Stocks [N1] this month.")
    census = an._resolve_number_handles(on, calls, handle_prose=True)
    assert on["tldr"] == "Stocks 1.62 MMT [N1] this month."
    assert census["substituted"] == 1


def test_figure_already_stated_still_wins_on_a_mixed_or_degraded_turn():
    """`_figure_already_stated` becomes dead code on the HAPPY path and MUST STAY for mixed and degraded
    turns -- a retry, a mid-flight `GRAPHRAG_HANDLE_PROSE=off` kill, or a model that simply ignored the
    contract. On those turns it is the only thing between the reader and a doubled figure (the measured
    cycle-7 shape: "was at 15.17 USD/mmbtu [N1] 15.17 USD/mmbtu")."""
    st = _st("Stocks were at [N1] 1.62 MMT as of the print.")
    census = an._resolve_number_handles(st, [_call("stocks", 1.62)], handle_prose=True)
    assert st["tldr"] == "Stocks were at [N1] 1.62 MMT as of the print."
    assert census["substituted"] == 0


def test_a_grouped_token_in_a_value_slot_is_severed_and_charged():
    """D-HP-11(b), folded from review C7. The shipped rule leaves a FULLY-RESOLVED group untouched --
    correct while the model also types the digit, and a defect the moment it does not: `[N1, N2]` then
    SHIPS TO THE READER standing where a figure belongs, re-minting D-PQ HANDLE-1, and G1 clause (2) is
    blind to it BECAUSE THE HANDLES RESOLVED. A group stands in for no single figure, so it may not be
    spliced; the clause goes and the turn is charged."""
    calls = [_call("stocks", 1.62), _call("use", 2.5)]
    on = _st("Use was at [N1, N2] overall.")
    census = an._resolve_number_handles(on, calls, handle_prose=True)
    assert "[N1, N2]" not in on["tldr"] and census["grouped_in_slot"] == 1
    assert census["handles_dropped"] == 2 and census["substituted"] == 0
    # ...and the CONTROL leaves it exactly where it is, which is what makes this a treatment effect.
    off = _st("Use was at [N1, N2] overall.")
    an._resolve_number_handles(off, calls)
    assert off["tldr"] == "Use was at [N1, N2] overall."
    # NO CUE -> no empty slot -> an ordinary co-citation, untouched on BOTH arms.
    beside = _st("Use fell sharply this year [N1, N2].")
    c2 = an._resolve_number_handles(beside, calls, handle_prose=True)
    assert beside["tldr"] == "Use fell sharply this year [N1, N2]." and c2["grouped_in_slot"] == 0


def test_the_sign_clause_prints_magnitude_for_a_polarity_metric_and_sign_for_everything_else():
    """D1, RESTATED AS CODE: the engine prints magnitude, unit, date and citation -- NOT SIGN. Under
    handle-only prose the model's verb already carries the direction, so splicing the raw signed value
    into the slot renders "fell to -0.31" on EVERY signed-delta row. abs() is therefore applied to the
    POLARITY TABLE class and to nothing else.

    A Z-SCORE IS NOT IN THAT CLASS AND MUST NOT BE: "-0.31 sigma" is a POSITION relative to a mean, the
    sign is the fact, and `_splice_fmt` stays byte-identical for it (`-0.3063197017144927 -> -0.30632`,
    the docstring's own example)."""
    signed = _st("Stocks fell to [N1].")
    an._resolve_number_handles(signed, [_call("stocks_delta", -0.306)], handle_prose=True)
    assert signed["tldr"] == "Stocks fell to 0.306 MMT [N1]."

    z = _st("The read sits at [N1].")
    an._resolve_number_handles(z, [_call("gas_zscore_5yr", -0.3063197017144927, unit="sigma")],
                               handle_prose=True)
    assert z["tldr"] == "The read sits at -0.30632 sigma [N1]."


def test_the_cycle10_reconciliation_holds_the_repair_counters_at_zero_on_both_arms():
    """D-HP RE-INTRODUCES A CODE PATH THAT WRITES A NUMERAL INTO PROSE, which is the capability cycle-10
    DELETED, and it must answer to that record. The distinction is the SLOT, not a fence: `_num_repair`
    second-guessed a number THE MODEL HAD WRITTEN (and the gate-7 op passed all four allowlist clauses
    and still corrupted a correct sentence); D-HP splices into a slot that is EMPTY BY CONTRACT, so there
    is nothing to certify and the splice carries no semantic judgement. Its only failure is a wrong row
    and its only remedy is deletion.
    THE MACHINE-CHECKABLE CONSEQUENCE: verify's rewrite counters stay 0/[] on the treatment arm too."""
    st = _st("Stocks fell to [N1].")
    report = vf.verify_citations(st, [], [_call("stocks_delta", -0.306)], handle_prose=True)
    assert report["repaired"] == 0 and report["repairs"] == []
    assert not hasattr(vf, "_unit_class") and not hasattr(vf, "_sentence_unit_class")


# ══ D-HP-13 -- DIRECTION VS SIGN ═════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("clause,metric,value,fires", [
    ("Stocks rose to", "ending_stocks_delta", -0.306, True),      # up verb, negative row
    ("Stocks fell to", "ending_stocks_delta", -0.306, False),     # agrees
    ("Stocks built to", "stocks_delta", -0.306, True),            # the STOCK-MOTION verb, bare metric name
    ("Stocks drew to", "ending_stocks_delta", -0.306, False),     # agrees
    ("The pace climbed to", "export_pace_change", -1.2, True),
    ("The pace eased to", "export_pace_change", -1.2, False),
])
def test_direction_vs_sign_fires_exactly_when_the_verb_contradicts_the_row(clause, metric, value, fires):
    """THE CHECK ITSELF. The model writes direction, the renderer knows the resolved row's sign, and
    under handle-only prose the sign is the ONLY place the direction is checkable -- D-HP-11's sign
    clause has just removed it from the page."""
    st = _st(f"{clause} [N1].")
    census = an._resolve_number_handles(st, [_call(metric, value)], handle_prose=True)
    assert bool(census["direction_sign_mismatch"]) is fires
    assert ("[N1]" not in st["tldr"]) is fires                    # the remedy is DELETION, never a reword
    if fires:
        assert st["tldr"] == ""                                   # ...the whole sentence, nothing backed


@pytest.mark.parametrize("clause,metric,value,why", [
    ("The ratio rose to", "su_ratio", 0.15, "not in the POLARITY TABLE -- a LEVEL, not a change"),
    ("The spread rose to", "corn_spread_delta", -0.5, "EXCLUDED: spread sign convention is per-leg"),
    ("The read rose to", "gas_zscore_5yr", -0.31, "EXCLUDED: a z is a position, not a change"),
    ("Stocks were at", "ending_stocks_delta", -0.306, "no licensed verb -- nothing claims a direction"),
    ("Stocks stayed unchanged at", "ending_stocks_delta", -0.306, "ditto, and 'unchanged' is not a verb"),
    ("Stocks rose to", "ending_stocks_delta", 0.0, "a zero row has no direction"),
])
def test_direction_vs_sign_refuses_every_case_it_cannot_ask_cleanly(clause, metric, value, why):
    """THE FOUR REFUSALS, AND THEY ARE THE POINT. Inverse-polarity metrics are the NORM in this estate --
    "stocks-to-use fell" means "tightened", a negative spread delta means "widened" -- so a naive
    sign-agreement test produces SYSTEMATIC false positives WHOSE REMEDY IS DELETING CORRECT PROSE. Every
    row here is a sentence the reader keeps."""
    st = _st(f"{clause} [N1].")
    census = an._resolve_number_handles(st, [_call(metric, value)], handle_prose=True)
    assert census["direction_sign_mismatch"] == 0, why
    assert "[N1]" in st["tldr"], why


def test_the_verb_is_bound_to_its_own_clause_never_a_neighbouring_one():
    """THE RULE THE DRAFT DID NOT HAVE, and the reason review G13 called it unmeasurable as written:
    nothing bound a verb to ONE of several handles in a multi-clause sentence. `_binding_clause` is that
    rule -- the last connective delimits -- so the verb that convicts a handle is always in the handle's
    own clause. Here "rose" belongs to the FIRST clause and cannot reach the handle behind "while"."""
    st = _st("Exports rose sharply while stocks fell to [N1].")
    census = an._resolve_number_handles(st, [_call("ending_stocks_delta", -0.306)], handle_prose=True)
    assert census["direction_sign_mismatch"] == 0
    assert an._binding_clause("Exports rose while stocks fell to ", 0, 34) == "stocks fell to "


def test_the_polarity_table_is_one_table_read_by_both_the_splice_and_the_check():
    """ONE TABLE, TWO READERS -- D-HP-13's own clause ("the same table is what D-HP-11's SIGN clause
    reads to decide abs(value), so the two cannot drift apart"). Two tables would mean splicing a
    magnitude while checking a sign the reader can no longer see."""
    assert an._polarity_entry("ending_stocks_delta")[0] == "_stocks_delta"    # longest suffix wins
    assert an._polarity_entry("stocks_delta")[0] == "_stocks_delta"          # ...and the bare name too
    assert an._polarity_entry("wasde_use_total") is None
    for excluded in ("corn_spread_delta", "gas_zscore_5yr", "basis_delta", "price_sigma"):
        assert an._polarity_entry(excluded) is None, excluded


# ══ D-HP-14 -- THE PERIOD SCOPE CHECK AND `wrong_slot_audit` ═════════════════════════════════════════

def test_the_period_scope_check_fires_only_when_both_sides_name_a_year_and_disagree():
    """D-HP-14(a). The outside measurement is 24-26% wrong-ENTITY with 0.0% wrong-TOOL in the same runs
    (the format layer gives NO signal on binding), 100% under TEMPORAL AMBIGUITY, and 0.0% for every
    UNAMBIGUOUS condition. A menu keyed by commodity x metric x PERIOD x vintage x source IS the
    temporal-ambiguity configuration, so the period axis is where the measured risk lives -- and it is
    the axis this estate can check with no vocabulary: both sides name a year or they do not."""
    disjoint = _st("MY2024/25 use ran to [N1].")
    c = an._resolve_number_handles(disjoint, [_call("use_total", 5.0, period="2020")], handle_prose=True)
    assert c["slot_scope_mismatch"] == 1 and disjoint["tldr"] == ""

    overlap = _st("MY2020 use ran to [N1].")
    c = an._resolve_number_handles(overlap, [_call("use_total", 5.0, period="2020")], handle_prose=True)
    assert c["slot_scope_mismatch"] == 0 and "5 MMT" in overlap["tldr"]

    silent = _st("Use ran to [N1].")                              # the clause names no year -> no question
    c = an._resolve_number_handles(silent, [_call("use_total", 5.0, period="2020")], handle_prose=True)
    assert c["slot_scope_mismatch"] == 0 and "5 MMT" in silent["tldr"]

    slash = _st("2024/25 use ran to [N1].")                       # the bare SLASH pair IS a declaration
    c = an._resolve_number_handles(slash, [_call("use_total", 5.0, period="2020")], handle_prose=True)
    assert c["slot_scope_mismatch"] == 1


def test_a_bare_reference_year_in_the_clause_never_convicts_the_slot():
    """THE FALSE-POSITIVE CLASS THIS CHECK WOULD OTHERWISE OWN, found by self-review and closed before it
    could delete anything. "Above the 2015 low, use ran to [N1]" names a REFERENCE year, not the scope of
    the figure in the slot, so a row dated 2026 reads as DISJOINT and the remedy DELETES A CORRECT
    SENTENCE. A detector whose remedy is deletion does not get to guess what a bare year means.
    THE CLAUSE SIDE THEREFORE READS DECLARED FORMS ONLY (`MY2025`, `MY2025/26`, `2025/26`); the ROW side
    keeps the full reading, which is the safe direction -- a wider row set can only ever produce an
    OVERLAP and silence the check, never fire it."""
    calls = [_call("use_total", 5.0, period="2020")]
    for clause in ("Above the 2015 low, use ran to", "As of 2026-05-30 use ran to",
                   "Since 1998 use ran to"):
        st = _st(f"{clause} [N1].")
        census = an._resolve_number_handles(st, calls, handle_prose=True)
        assert census["slot_scope_mismatch"] == 0, clause
        assert "5 MMT" in st["tldr"], clause
    assert an._period_years("above the 2015 low") == {"2015"}                    # ...seen
    assert an._period_years("above the 2015 low", declared_only=True) == set()   # ...never a scope


def test_wrong_slot_audit_is_a_projection_of_the_pass_that_actually_deleted_the_prose():
    """THE SHAPE IS FROZEN IN `tracekeys` BECAUSE FOUR CONSUMERS JOIN ON IT, and it is a PROJECTION of
    the render census rather than a second measurement -- two producers for one risk is how a census
    comes to read 0 while the page lost a sentence.
    R11 reads it PER ROW (`mis_bound_count` >= 3 on any single row is recorded BY ID), which is why the
    column is per turn and not per run."""
    census = an._resolve_number_handles(_st("MY2024/25 use ran to [N1]."),
                                        [_call("use_total", 5.0, period="2020")], handle_prose=True)
    audit = an._wrong_slot_audit(census)
    assert set(audit) == {"scope_checked", "scope_mismatch", "direction_checked", "direction_mismatch"}
    assert audit["scope_checked"] == 1 and audit["scope_mismatch"] == 1
    assert audit["direction_checked"] == 0                        # the scope refusal came first
    assert an._wrong_slot_audit(None) == {"scope_checked": 0, "scope_mismatch": 0,
                                          "direction_checked": 0, "direction_mismatch": 0}


# ══ D-HP-12 -- THE DIGIT-LINT ════════════════════════════════════════════════════════════════════════

def test_the_lint_charges_in_verify_and_exempts_an_e_cited_sentence():
    """R3, OPTION (b) AS RATIFIED. 10.5% of all typed numerals exist ONLY inside [E] chunk prose, so a
    menu built from served_rows cannot express them and a hard ban would lose 850 real figures per
    corpus. The exemption keeps the prose whole TODAY and the HARD COUNTER prices the hole -- which is
    what decides whether option (a) (the `[Q]` span handle) is worth its own phase.
    THE CHARGE IS IN ONE LEDGER (`by_rule`), so the class scan -- this wave's primary gate -- sees it."""
    st = _st("Stocks hit 4,250 MYR last month.", "Palm rose 12.5% [E1]. Nothing numeric here.")
    ev = [{"source": "mpob", "source_key": "k", "date": "2026-01-01", "text": "palm rose 12.5% on stocks"}]
    report = vf.verify_citations(st, ev, [], handle_prose=True)
    assert report["by_rule"].get("bare_digit") == 1               # the tldr sentence, and only it
    assert report["bare_digit"] == {"charged": 1, "e_cited": 1}
    # ...and the CONTROL charges nothing and carries no such key at all (the OFF-arm-clean rule).
    off = vf.verify_citations(_st("Stocks hit 4,250 MYR last month."), ev, [])
    assert "bare_digit" not in off["by_rule"] and "bare_digit" not in off


@pytest.mark.parametrize("sent,verdict", [
    ("Stocks hit 4,250 MYR.", "bare_digit"),
    ("Palm rose 12.5% [E1].", "e_cited"),
    ("Palm rose 12.5% [E1, E2].", "e_cited"),                     # grouped
    ("Palm rose 12.5% [E1-E4].", "e_cited"),                      # ranged
    ("Palm rose 12.5% [3].", "e_cited"),                          # the bare lead IS the [E] namespace
    ("Use was at [N1].", None),                                   # no claim magnitude of its own
    ("Stocks hit 4,250 MYR [N1].", "bare_digit"),                 # an [N] is a SLOT, never a source
    ("The 5-year mean held.", None),                              # the extractor's own exemptions ...
    ("As of 25 July 2026 the print landed.", None),               # ... six of them, unchanged
])
def test_bare_digit_verdict_is_the_one_producer_for_both_halves(sent, verdict):
    """ONE PRODUCER (D-HP-3): the charge in verify and the deletion in the renderer call THIS, so they
    cannot disagree about what a bare digit is or about the exemption. The extractor underneath is
    `_claim_number_spans` -- the one `dhp_census.json` itself ran, so every count in this wave is
    denominated in the same producer every census percentage is."""
    assert vf.bare_digit_verdict(sent) == verdict


def test_the_remedy_deletes_and_it_runs_before_the_splice_or_it_would_delete_the_engines_own_work():
    """THE ORDER IS THE WHOLE SAFETY OF THE REMEDY, and this test is its NEGATIVE CONTROL.
    `_resolve_number_handles` WRITES row values into the prose. Running the lint after it would read the
    ENGINE's digits as the MODEL's and delete every sentence the renderer had just filled in -- the lint
    fining the estate for doing its job. The second half of this test reproduces exactly that, so if the
    stack order is ever inverted the reproduction is on the record rather than in production."""
    calls = [_call("use", 2.5)]
    st = _st("Stocks hit 4,250 MYR last month.", "Use was at [N1] overall.")
    census = an._drop_bare_digit_sentences(st, calls)
    assert census["sentences_dropped"] == 1 and st["tldr"] == ""
    assert st["mechanism"] == "Use was at [N1] overall."           # the handled sentence is untouched

    spliced = _st("Use was at [N1] overall.")
    an._resolve_number_handles(spliced, calls, handle_prose=True)
    assert "2.5 MMT" in spliced["tldr"]
    assert an._drop_bare_digit_sentences(dict(spliced), calls)["sentences_dropped"] == 1   # <- the proof


def test_the_remedy_severs_when_a_resolved_handle_survives_outside_the_cut():
    """"...with the same sever rule when a resolved handle shares the clause". The sentence keeps a
    grammatical head and keeps its backed content; only the clause that typed a number goes."""
    st = _st("Use was at [N1], while stocks hit 4,250 MYR.")
    census = an._drop_bare_digit_sentences(st, [_call("use", 2.5)])
    assert census["clauses_severed"] == 1 and census["sentences_dropped"] == 0
    assert "[N1]" in st["tldr"] and "4,250" not in st["tldr"]


# ══ D-HP-10 / D-HP-9 -- THE [E] SIDE ════════════════════════════════════════════════════════════════

def test_verify_resolves_an_in_range_e_handle_positionally_under_handle_prose_only():
    """D-HP-9's MANDATORY CLAUSE, and it is the single most consequential correction in the plan's fold.
    `report['resolved']` is built EXCLUSIVELY from the model's ledger, so with `sources` dropped from the
    tool schema it would stay {} and SIX consumers go dark -- including `_prune_orphan_evidence_handles`,
    which would then prune EVERY [E] handle from the prose, and the LIVE FE chip path, which reads
    `trace.citation_verifier.resolved` and nothing else.
    THE ORDER IS PART OF THE CONTRACT: minting here (not synthesising a LEDGER before verify) is what
    keeps `fabricated_citation` a real check instead of a tautology."""
    uniq = [{"source": "mpob", "source_key": "k", "date": "2026-01-01", "text": "costs fell"},
            {"source": "usda", "source_key": "k2", "date": "2026-02-01", "text": "exports rose"}]
    st = _st("Costs fell [E1] and exports rose [E2].")
    report = vf.verify_citations(st, uniq, [], handle_prose=True)
    assert set(report["resolved"]) == {"1", "2"}
    assert report["resolved"]["2"]["source_key"] == "k2"           # the payload shape the FE joins on
    assert "undeclared_unsupported" not in report["by_rule"]
    assert "fabricated_citation" not in report["by_rule"]
    # THE CONTROL: with no ledger and the flag off, nothing resolves -- which is the defect, pinned.
    off = vf.verify_citations(_st("Costs fell [E1]."), uniq, [])
    assert off["resolved"] == {}


def test_the_full_e_chain_leaves_the_prune_with_nothing_to_do():
    """D-HP-9's PIN, end to end: "on a handle-prose turn with N distinct prose [E] indices,
    `len(verifier['resolved']) == N`, `_document_source_rows` emits N rows, and
    `_prune_orphan_evidence_handles` returns 0". The prune is the join's last-resort backstop; a
    non-zero return here would mean the reader lost every receipt in the flip."""
    uniq = [{"source": "mpob", "source_key": "k", "date": "2026-01-01", "text": "costs fell"},
            {"source": "usda", "source_key": "k2", "date": "2026-02-01", "text": "exports rose"}]
    st = _st("Costs fell [E1] and exports rose [E2].")
    report = vf.verify_citations(st, uniq, [], handle_prose=True)
    an._synthesize_sources(st, report)
    assert len(report["resolved"]) == 2 and len(st["sources"]) == 2
    assert all(row.get("source_key") for row in st["sources"])     # the 6.5 click-to-page locator's input
    assert an._prune_orphan_evidence_handles(st, report) == 0
    assert "[E1]" in st["tldr"] and "[E2]" in st["tldr"]


def test_prose_handles_counts_on_both_arms_and_mutates_on_one():
    """D-HP-10's census -- the `bare_digit_count` posture, and for the same reason: G1 reads
    control-vs-treatment on the SAME column, so a census that exists only on the treatment arm gives the
    comparison no denominator. With the flag off this is a pure read.
    `substituted` IS STRUCTURALLY 0 IN THIS BUILD and that is not a bug: the [E] splice payload would be
    a date / era label / series scope, all three of which D-HP-7 puts on the NOT-IN-SCOPE list, sequenced
    after G1/G2. The key exists so the column shape does not move when they land."""
    uniq = [{"source": "mpob", "source_key": "k", "date": "2026-01-01", "text": "costs fell"}]
    off = _st("Costs fell [E1] and [E9].")
    census = an._resolve_evidence_handles(off, uniq)
    assert census == {"substituted": 0, "handles_dropped": 0, "sentences_dropped": 0, "unresolvable": 1}
    assert off["tldr"] == "Costs fell [E1] and [E9]."               # counted, NOT mutated

    on = _st("Costs fell [E1] and [E9].")
    census = an._resolve_evidence_handles(on, uniq, handle_prose=True)
    assert census["unresolvable"] == 1 and census["handles_dropped"] == 1
    assert "[E9]" not in on["tldr"] and "[E1]" in on["tldr"]


def test_an_unresolvable_e_handle_standing_in_a_value_slot_kills_the_sentence():
    """The [E] twin of D-PQ HANDLE-1's own rule. `verify._check_evidence_handle` is a LEXICAL-OVERLAP
    test, so an index pointing at the WRONG-BUT-REAL item passes today and is reader-invisible, and there
    has never been an [E] equivalent of the [N] value-splice. Under handle-only prose that gap is not
    cosmetic: the handle IS the claim, and a de-handled "the print was at " is worse than silence."""
    uniq = [{"source": "mpob", "source_key": "k", "date": "2026-01-01", "text": "costs fell"}]
    st = _st("The latest print was at [E9].")
    census = an._resolve_evidence_handles(st, uniq, handle_prose=True)
    assert st["tldr"] == "" and census["sentences_dropped"] == 1


# ══ THE CONTROL ARM, ASSERTED AS ONE PROPERTY ═══════════════════════════════════════════════════════

def test_the_control_arm_is_the_pre_dhp_renderer_on_every_shape_but_the_declared_one():
    """THE ARM IS THE BUNDLE, AND THE OFF ARM IS THE PRE-D-HP RENDERER. Every clause of the treatment --
    the flip, the two binding refusals, `grouped_in_slot`, the sign clause, the lint's remedy, the [E]
    pass's mutation -- is gated on ONE argument, so the control is provable by construction.

    NO EXCEPTIONS REMAIN (H1 FIX Z8). The first build carried ONE: the TOKEN GRAMMAR was widened on both
    arms, which is defensible under section 2's constant-across-arms law and is NOT what the orchestrator's
    byte-identity mandate permits -- and the priced delta was not the whole delta, because a suffixed token
    in a value slot DELETES A CONTROL-ARM SENTENCE and moves the control arm's own `unresolvable` /
    `sentences_dropped` census, the two columns G1 clause (2) and D-HP-17 item 4 read. The grammar is now
    the treatment's (`_n_token_rx`), so this test asserts the control renderer with nothing subtracted."""
    calls = [_call("ending_stocks_delta", -0.306), _call("use", 2.5)]
    uniq = [{"source": "mpob", "source_key": "k", "date": "2026-01-01", "text": "costs fell"}]
    body = ("Stocks rose to [N1] while use was at [N1, N2] and costs hit 4,250 MYR. "
            "Costs fell [E1] and [E9].")
    st = _st(body, body)
    n = an._resolve_number_handles(st, calls)
    e = an._resolve_evidence_handles(st, uniq)
    # the shipped splice still fires on the CUE (that is D-PQ HANDLE-1 and it predates this wave), the
    # grouped token is still left standing, the bare digit is still the model's, the [E] pass is a read.
    assert st["tldr"] == st["mechanism"] == body.replace("rose to [N1]", "rose to -0.306 MMT [N1]")
    assert "[N1, N2]" in st["tldr"] and "4,250" in st["tldr"] and "[E9]" in st["tldr"]
    assert n["substituted"] == 2 and n["handles_dropped"] == 0
    assert set(n) == {"substituted", "handles_dropped", "sentences_dropped", "unresolvable"}
    assert set(e) == {"substituted", "handles_dropped", "sentences_dropped", "unresolvable"}
    # ...and the same body on the treatment arm is materially changed, or the control proves nothing.
    on = _st(body, body)
    n_on = an._resolve_number_handles(on, calls, handle_prose=True)
    assert on["tldr"] != st["tldr"]
    assert set(n_on) - set(n) == {"grouped_in_slot", "direction_sign_mismatch", "slot_scope_mismatch",
                                  "scope_checked", "direction_checked", "binding_refused"}


def test_the_suffixed_token_is_the_treatments_grammar_and_the_control_arm_is_bytes():
    """H1 FIX Z8, PINNED AS BYTES IN BOTH DIRECTIONS.

    THE MEASUREMENT STANDS (`data/dhp_h1_suffix_exposure.json`, $0, stored artifacts): over 430 audited
    answers carrying 51,863 handle tokens, suffixed tokens in the model's own prose = 2 at `preverify_*`,
    2 at `postverify_*`, 1 at `verified_*` -- i.e. ~1 token per 430 answers ALREADY REACHES THE READER as
    literal text. That is D-PQ HANDLE-1's own defect class alive in production, and it is REAL.

    WHAT CHANGED IS WHERE THE FIX IS ALLOWED TO LAND. Shipping the widening ungated moved the CONTROL arm:
    a suffixed token in a VALUE SLOT is `standin` + unresolvable, so it takes the WHOLE SENTENCE. Reproduced
    below on the control arm -- an A/B whose control renderer deletes a sentence the pre-wave renderer kept
    is not a control. The pre-existing reader exposure is recorded for the post-gate consolidation; it does
    not get fixed from inside the arm that is being measured.

    THE TREATMENT HALF IS UNCHANGED: seen, refused, never bound."""
    calls = [_call("stocks", 1.62)]
    # CONTROL: byte-identical to the pre-H1 renderer -- the token is invisible and the sentence survives.
    off = _st("Nothing here [N1b].", "US wheat exports were [N1b] this week.")
    c_off = an._resolve_number_handles(off, calls)
    assert off["tldr"] == "Nothing here [N1b]."                       # inert debris, as it was pre-wave
    assert off["mechanism"] == "US wheat exports were [N1b] this week."   # ...and NO sentence was deleted
    assert c_off == {"substituted": 0, "handles_dropped": 0, "sentences_dropped": 0, "unresolvable": 0}
    # TREATMENT: seen, refused, removed -- and never bound to call 1's headline.
    on = _st("Nothing here [N1b].", "US wheat exports were [N1b] this week.")
    c_on = an._resolve_number_handles(on, calls, handle_prose=True)
    assert "[N1b]" not in on["tldr"] and "[N1b]" not in on["mechanism"]
    assert "1.62" not in on["tldr"] and "1.62" not in on["mechanism"]
    assert c_on["substituted"] == 0, "a suffixed member was BOUND -- the trap, not the defusal"
    assert c_on["unresolvable"] == 2 and c_on["sentences_dropped"] == 1


def test_composition_census_n_evidence_carries_its_post_h0_meaning(monkeypatch):
    """RESIDUAL 10.9(2), MACHINE-CHECKED. `composition_census.n_evidence` is a REGISTERED COLUMN whose
    DENOMINATOR moved across the H0 boundary on the desk lanes: it counted the PRE-DEDUP evidence list
    and now counts the deduped `uniq`. `tracekeys` carries the boundary in the column's consumer note --
    but a note is a sentence, and this is the pin that makes the meaning enforceable.

    THE POST-H0 MEANING, PINNED: on the menu-on (desk) lane `n_evidence` is the SAME integer the GROUNDING
    LEDGER states to the model, i.e. DISTINCT EVIDENCE DOCUMENTS -- one row per `source_key`. That
    identity is the whole point: the number the composition mandates reason about must be the number the
    model was told it holds, or the mandate is arguing about a different corpus than the writer has.
    A CROSS-BOUNDARY READ OF THIS COLUMN POOLS TWO DEFINITIONS. Nothing gates on it (D-MW-17,
    recorded-only), so no gate clause moves -- which is exactly why it needed writing down rather than
    discovering."""
    import pathlib
    src = pathlib.Path(an.__file__).read_text(encoding="utf-8")
    # ONE local, TWO consumers, in that order: the GROUNDING LEDGER the model reads, then the census the
    # composition mandates reason about. A second derivation is how the two come to disagree about N.
    n_ev = src.index("n_ev = (len(_uniq) if _menu_on")
    assert src.index("_grounding_ledger(n_ev, n_num, menu_on=_menu_on)", n_ev) > n_ev
    assert src.index("n_evidence=n_ev)", n_ev) > n_ev
    # ...and the MENU-OFF (dossier) lane keeps the PRE-dedup count on the SAME line, deliberately:
    # nothing numbered anything there, so the honest statement is the loose cap the pre-D-HP prompt made.
    assert 'else sum(len(getattr(n, "evidence", []) or []) for n in sg.nodes))' in src[n_ev:n_ev + 300]
    # ...and `_uniq` IS the deduped list, which is what makes the post-H0 meaning "distinct DOCUMENTS".
    rows = [{"source": "a", "source_key": "k", "date": "2026-01-01", "text": "x"},
            {"source": "a", "source_key": "k", "date": "2026-01-01", "text": "y"},
            {"source": "b", "source_key": "k2", "date": "2026-01-01", "text": "z"}]
    assert len(an._uniq_evidence(rows)) == 2 < len(rows)
    # THE BOUNDARY IS RECORDED WHERE THE COLUMN'S CONSUMERS LOOK -- the registry, not only a plan.
    from leviathan.graphrag import tracekeys as tk
    import inspect
    reg_src = inspect.getsource(tk)
    assert "n_evidence" in reg_src and "pre-dedup" in reg_src


def test_the_one_knob_is_a_preset_and_the_env_can_only_ever_kill(monkeypatch):
    """R9, from the RENDERER's side (`eval._handle_prose_arm` pins the same law from the artifact's).
    The enabling lever is a PRESET because the escalation seam swaps the knob dict WHOLE
    (orchestrator.py:2138-2139) -- an env-only design would strip the treatment MID-TURN on two of the
    four judged gates. The env is a ONE-WAY KILL: it cannot turn the feature on, so it cannot drift a
    gate arm and it cannot stamp an arm that did not run."""
    monkeypatch.delenv("GRAPHRAG_HANDLE_PROSE", raising=False)
    assert an._handle_prose_on({"handle_prose": True}) is True
    assert an._handle_prose_on({}) is False and an._handle_prose_on(None) is False
    for on in ("on", "1", "true", "deep_hp", "yes"):
        monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", on)
        assert an._handle_prose_on({}) is False, f"the env turned the treatment ON: {on}"
    for kill in ("off", "0", "false", "kill", "OFF", " off "):
        monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", kill)
        assert an._handle_prose_on({"handle_prose": True}) is False, kill


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# H1 ADVERSARIAL-REVIEW FIXES (Z1/Z2/Z4/Z6/Z12) -- the render half
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def _period_call(metric: str, value, period_label: str) -> dict:
    """A call whose ROW LABEL names a crop year, so `_slot_scope_mismatch` has a row side to compare."""
    return {"query": {"table": "silver_wasde", "metric": metric, "commodity": "corn",
                      "period": period_label},
            "rows": [{"value": value, "unit": "mil bu", "period": period_label}], "status": "ok",
            "shown": [value]}


def test_a_binding_refusal_is_not_an_unresolvable_handle():
    """FIX Z2. D-HP-17 item 4 defines `unresolvable` as "the model addressed a receipt that does not
    exist". A D-HP-13/D-HP-14 refusal is the OPPOSITE state -- the receipt exists and resolved, and this
    pass declined to bind it.

    THE TWO PRE-REGISTERED CLAUSES WERE MUTUALLY UNSATISFIABLE BEFORE THIS. G1 clause (2) requires
    `number_handles.unresolvable == 0` on EVERY treatment row while D-HP-17 2c / R11 budget 15 mis-bound
    events, so ONE legitimate fire of the wave's own designed behaviour failed the gate outright. It also
    polluted `handles_unresolvable`, which the successor family calls "the wave's residual"."""
    st = _st("Corn ending stocks rose to [N1] on the month.")
    census = an._resolve_number_handles(st, [_call("ending_stocks_delta", -5.058)], handle_prose=True)
    assert census["direction_sign_mismatch"] == 1                # the refusal fired...
    assert census["sentences_dropped"] == 1                      # ...and the removal is unchanged
    assert census["unresolvable"] == 0                           # G1 clause (2) computes on the design
    assert census["binding_refused"] == 1                        # ...on its own counter, per item 4
    # ...and the successor family's residual is no longer polluted by the wave's own designed behaviour
    from leviathan.graphrag import emf as emfmod
    q = emfmod.quality_counters({"citation_verifier": {"enabled": True, "by_rule": {}},
                                 "number_handles": census})
    assert q["handles_unresolvable"] == 0


def test_a_genuinely_missing_receipt_still_counts_as_unresolvable():
    """The other direction of FIX Z2, or the counter would mean nothing: an out-of-range index IS "the
    model addressed a receipt that does not exist", and it keeps its defined meaning."""
    st = _st("Stocks stood at [N9] last month.")
    census = an._resolve_number_handles(st, [_call("stocks", 1.62)], handle_prose=True)
    assert census["unresolvable"] == 1 and census["binding_refused"] == 0


def test_scope_checked_counts_comparisons_never_attempts():
    """FIX Z12. `_wrong_slot_audit`'s docstring promises "PERIOD checks only ... so the column never
    claims coverage it does not have", and the shipped counter incremented for every solitary resolved
    handle -- before `_slot_scope_mismatch` decided anything, and therefore on rows whose clause names no
    period at all. A coverage column that counts attempts is a coverage column that lies."""
    silent = _st("Stocks stood at [N1] last month.")             # no DECLARED crop-year scope anywhere
    c1 = an._resolve_number_handles(silent, [_call("stocks", 1.62)], handle_prose=True)
    assert c1["scope_checked"] == 0 and c1["slot_scope_mismatch"] == 0
    # ...and a row where BOTH sides speak is counted, which is what the column promises to mean
    spoke = _st("MY2025/26 ending stocks stood at [N1] on the report.")
    c2 = an._resolve_number_handles(spoke, [_period_call("ending_stocks", 1500, "2025/26")],
                                    handle_prose=True)
    assert c2["scope_checked"] == 1 and c2["slot_scope_mismatch"] == 0
    assert an._slot_scope_mismatch("no period here", _call("stocks", 1.0), 1) == (False, False)


def test_the_three_render_classes_reach_the_one_strip_ledger():
    """FIX Z1/Z6. `emf.MIS_BOUND_CLASSES` and G1 clause (4)'s CLASS SCAN both read `by_rule`, and these
    three classes were written ONLY into `trace['number_handles']` -- so `mis_bound_count` read
    `direction_sign_mismatch` as 0 forever and the class scan was blind to three of the four D-HP-native
    classes it declares. That is the D5 failure emf.py's own comment names: a family that congratulates
    the wave.

    `stripped` MOVES WITH THEM, because every `by_rule[x] += 1` in verify.py is paired with one and each
    of these events DID remove prose from the reader's page."""
    verifier = {"enabled": True, "stripped": 3, "by_rule": {"bare_digit": 2}}
    census = {"slot_scope_mismatch": 4, "direction_sign_mismatch": 7, "grouped_in_slot": 1}
    assert an._fold_render_classes(verifier, census) == 12
    assert verifier["by_rule"] == {"bare_digit": 2, "slot_scope_mismatch": 4,
                                   "direction_sign_mismatch": 7, "grouped_in_slot": 1}
    assert verifier["stripped"] == 15 == sum(verifier["by_rule"].values()) + 1   # 1 pre-existing strip
    # a CONTROL row's census carries none of these keys, so the ledger is byte-identical (OFF-arm clean)
    clean = {"enabled": True, "stripped": 3, "by_rule": {"bare_digit": 2}}
    assert an._fold_render_classes(clean, {"substituted": 2, "unresolvable": 0}) == 0
    assert clean == {"enabled": True, "stripped": 3, "by_rule": {"bare_digit": 2}}


def test_the_class_scan_and_the_metric_read_one_location_after_the_fold():
    """FIX Z1/Z6, END TO END through the two consumers that were blind. The fold is what makes the class
    scan (section 2's named primary regression detector) and R11's ceiling read the SAME numbers."""
    from leviathan.graphrag import emf as emfmod
    verifier = {"enabled": True, "stripped": 0, "by_rule": {}}
    census = {"slot_scope_mismatch": 4, "direction_sign_mismatch": 7, "grouped_in_slot": 1}
    an._fold_render_classes(verifier, census)
    trace = {"citation_verifier": verifier, "number_handles": census,
             "wrong_slot_audit": an._wrong_slot_audit(census)}
    assert emfmod.quality_counters(trace)["mis_bound_count"] == 11        # 4 + 7, projection deduped
    for cls in ("slot_scope_mismatch", "direction_sign_mismatch", "grouped_in_slot"):
        assert cls in verifier["by_rule"], f"the class scan is still blind to {cls}"


def _licence(st: dict, *fields: str) -> vf._VerifyReport:
    """The report `verify` would have returned had it stripped a handle out of the value slot at the end
    of EVERY sentence in `fields`: one `{field, key, src}` seam per cut, in verify's own shape, with
    verify's own normalization AND verify's own producer tag (H1 FIX X2). Used where a test is pinning the
    CUE half of W1's two conditions and the licence is not what is under test -- the licence itself is
    pinned end to end, off the real producers, by the tests below and by test_dhp_seam_provenance.py."""
    rep = vf._VerifyReport({"enabled": True, "stripped": 0, "by_rule": {}})
    for f in (fields or ("tldr", "mechanism")):
        text = st.get(f) or ""
        pos = 0
        while pos < len(text):
            s0, s1 = an._handle_sentence_span(text, pos)
            if s1 <= pos:
                pos += 1
                continue
            core = text[s0:s1].rstrip()
            while core and core[-1] in ".!?;:,":
                core = core[:-1].rstrip()
            rep.strip_seams.append({"field": f, "src": an._SEAM_SRC_VERIFY,
                                    "key": vf._seam_key(text[s0 + len(core):][:vf._SEAM_LOOKAHEAD])})
            pos = s1
    return rep


def test_a_value_slot_emptied_by_a_verifier_strip_takes_its_whole_sentence():
    """FIX Z4, RE-PINNED END TO END THROUGH THE REAL PRODUCER (H1 FIX W1). `verify_citations` runs BEFORE
    the handle passes and removes a convicted handle span BY POSITION. Under D-HP-7 the slot is empty by
    contract, so the sentence loses its figure AND its handle and renders as a truncated fragment -- and
    the handle passes cannot help, because the token is already gone. `_tidy_handle_debris` closes BRACKET
    frames, not a dangling value word.

    THIS IS THE GENERAL CASE ON THE TREATMENT ARM: each of the four RESIDUAL classes G1 declares survive
    by construction leaves exactly this state, on the treatment arm and only there (on control the model
    also typed the digit, so the same strip leaves a complete sentence).

    THE FIXTURE IS NOW THE PIPELINE, not a hand-typed fragment: `verify` convicts the handle, records its
    own seam, and THAT is what licenses the cut. Both shapes are covered -- the FIELD-FINAL sentence
    (whose successor text is a bare ".") and a mid-field one."""
    st = _st("US corn ending stocks stood at [N9].",
             "The export ban took effect at [N9]. Trade continued.")
    report = vf.verify_citations(st, [], [_call("stocks", 1.62)], handle_prose=True)
    assert st["tldr"] == "US corn ending stocks stood at."          # the defect, reproduced
    assert report["by_rule"]["index_out_of_range"] == 2 and len(report.strip_seams) == 2
    census = an._drop_slot_orphan_sentences(st, report)
    assert st["tldr"] == ""
    assert st["mechanism"] == "Trade continued."
    assert census["sentences_dropped"] == 2
    # ...and a COMPLETE sentence -- the control arm's own shape, where the model typed the digit -- stays
    # EVEN WITH A LICENCE AT ITS OWN CUT: both conditions are required, so this pins the CUE half.
    keep = _st("US corn ending stocks stood at 12.5 mil bu.", "Trade continued near 4,250.")
    assert an._drop_slot_orphan_sentences(keep, _licence(keep)) == {"sentences_dropped": 0}
    assert keep["tldr"] == "US corn ending stocks stood at 12.5 mil bu."


def test_w1_a_clean_sentence_that_merely_ends_on_a_cue_is_never_deleted():
    """H1 FIX W1 -- FINDING NF-1, THE BLOCKER, AND THE REASON THIS PASS HAS A PRECONDITION AT ALL.

    Shipped as a CUE-ONLY scan, this pass deleted any sentence whose last word was one of ~35 value
    words, whether or not a handle had ever stood there. MEASURED over the estate's own stored prose (45
    artifacts, 1,724 prose fields, 32,557 sentences by this pass's own sentence walk): 314 deletions,
    0.96%, almost all of them grammatically complete and fully backed. Treatment-gated, so 100% of that
    delta lands on G2 (fluency do-no-harm) and on the reader.

    EVERY SENTENCE BELOW IS ONE THIS FILE'S OWN ESTATE WROTE and the cue-only pass destroyed: "at this
    as-of" matches `\\bof\\s+$` across the hyphen, and "Production vs. exports ..." loses its SUBJECT
    because "vs." reads as a terminator AND "vs" is itself a cue.

    THREE ARMS, because the third is the one a weaker fix would still fail: no report at all, a report
    from a turn that stripped NOTHING, and a report carrying a REAL seam for a DIFFERENT sentence in the
    SAME field -- adjacency to a strip is not a licence, the strip must be at THIS sentence's own cut."""
    clean = ("No high-confidence price-supportive driver is documented as active at this as-of.",
             "Production vs. exports diverged in June.",
             "That is a dated instance, not a current-state read.",
             "The sharpest observable the record carries.",
             "Stocks are higher than they were.",
             "The spread is the widest it has been.",
             "That is what the debate is about.")
    for frag in clean:
        for rep in (None, vf._VerifyReport({"enabled": True, "by_rule": {}})):
            st = _st(frag, frag)
            assert an._drop_slot_orphan_sentences(st, rep) == {"sentences_dropped": 0}, frag
            assert st["tldr"] == frag and st["mechanism"] == frag, frag
    # ARM 3: a REAL strip, in the same field, one sentence away -- and the clean neighbours all survive.
    st = _st("", " ".join(clean) + " Use totalled at [N9]. " + clean[0])
    report = vf.verify_citations(st, [], [_call("stocks", 1.62)], handle_prose=True)
    assert report.strip_seams, "the fixture must actually strip, or arm 3 proves nothing"
    assert an._drop_slot_orphan_sentences(st, report) == {"sentences_dropped": 1}
    assert "Use totalled at." not in st["mechanism"]
    for frag in clean:
        assert frag in st["mechanism"], frag


def test_w1_the_licence_is_the_strip_record_and_nothing_else():
    """H1 FIX W1, THE TRIGGER CONDITION ITSELF, both directions on ONE fixture.

    `_slot_orphan_licensed` joins on the seam a SLOT-EMPTYING producer recorded at the cut -- verify's own
    normalized successor text -- so it is the STRIP that fires this pass, never the sentence's shape. The
    two edges that matter: a SHORT tail (the field's last sentence, successor ".") is matched WHOLE,
    because a floor like `_seam_adjacent`'s 8 characters would blind exactly the commonest case; and a seam
    recorded in the OTHER field never licenses a cut here.

    EVERY SEAM HERE CARRIES ITS PRODUCER TAG (H1 FIX X2) -- the tag half of the trigger is pinned in
    test_dhp_seam_provenance.py, and a fixture without one is refused, so it cannot be written by accident.
    A matched seam is CONSUMED (X3a), which is why each list below is used exactly once."""
    text = "US corn ending stocks stood at."
    _v = an._SEAM_SRC_VERIFY
    assert an._slot_orphan_licensed([{"field": "tldr", "key": ".", "src": _v}], "tldr", ".") is True
    assert an._slot_orphan_licensed([{"field": "mechanism", "key": ".", "src": _v}], "tldr", ".") is False
    assert an._slot_orphan_licensed([], "tldr", ".") is False
    # a long tail keeps the estate's 32-char prefix rule, so one sanitize edit deep inside it is survivable
    tail = ". Trade continued through the second half of the marketing year."
    assert an._slot_orphan_licensed([{"field": "tldr", "key": vf._seam_key(tail), "src": _v}],
                                    "tldr", tail) is True
    assert an._slot_orphan_licensed([{"field": "tldr", "src": _v,
                                      "key": vf._seam_key(". Something else entirely.")}],
                                    "tldr", tail) is False
    # ...and the legacy/fixture `after` spelling still joins, as it does for TIDY-2
    st = _st(text)
    rep = vf._VerifyReport({"enabled": True, "by_rule": {}})
    rep.strip_seams.append({"field": "tldr", "after": ".", "src": _v})
    assert an._drop_slot_orphan_sentences(st, rep)["sentences_dropped"] == 1 and st["tldr"] == ""


def test_the_slot_orphan_drop_covers_the_four_residual_classes_and_both_namespaces():
    """FIX Z4 on the GENERAL case the finding names: the four classes that survive by construction
    (no_lexical_overlap, quote_mismatch, foreign_regime_name, index_out_of_range) and BOTH handle
    namespaces. Each is one positional strip inside a value slot, so each leaves the same fragment --
    driven here through `verify` itself, so the strip that licenses the cut is a real one."""
    for frag in ("Stocks fell to [N9].", "Use totalled [N9].", "The print came in at [N9].",
                 "Exports were [E9]."):
        st = _st(frag)
        report = vf.verify_citations(st, [], [_call("stocks", 1.62)], handle_prose=True)
        assert "[" not in st["tldr"], frag                      # the strip happened
        assert an._drop_slot_orphan_sentences(st, report)["sentences_dropped"] == 1, frag
        assert st["tldr"] == "", frag


def test_the_slot_orphan_drop_mints_the_seam_tidy_2_repairs():
    """FIX Z4 + Z12: a whole-sentence drop opens a paragraph seam, and TIDY-2 joins on
    `report.strip_seams` -- which only `verify._verify_field` ever populated. The render-side cuts mint
    their own, in verify's own shape, so the repair pass can see them."""
    st = _st("", "Stocks fell to. that left the balance sheet tight.")
    report = _licence(st)
    n0 = len(report.strip_seams)                    # ...the LICENCE seams; the mint is what comes after
    an._drop_slot_orphan_sentences(st, report)
    minted = report.strip_seams[n0:]
    assert minted and minted[0]["field"] == "mechanism"
    assert minted[0]["key"].startswith("that left the balance")
    # ...tagged as a WHOLE-SENTENCE producer (H1 FIX X2), so TIDY-2 takes it and the licence never does
    assert minted[0]["src"] == an._SEAM_SRC_SLOT_ORPHAN
    assert an._SEAM_SRC_SLOT_ORPHAN not in an._SLOT_EMPTYING_SEAM_SRCS
    # the counters are UNTOUCHED: `strip_seams` is a POSITION carrier, never a count
    assert report.get("stripped") == 0 and report["by_rule"] == {}


def test_w2_a_deleted_slot_orphan_reaches_the_one_strip_ledger():
    """H1 FIX W2 -- FINDING NF-2. The pass DELETES SENTENCES and had no counterpart anywhere: no `by_rule`
    class, no successor term, no column. A G2 fluency delta it caused would have had no readable cause in
    any G1/G2 artifact -- the C2/U3 silent class, re-minted on the one pass whose false-fire risk NF-1
    measured at 314/32,557.

    IT FOLDS UNDER THE Z1 RULE: `by_rule` and `stripped` move together, so the ledger's own invariant
    `sum(by_rule.values()) == stripped` survives the fold."""
    st = _st("US corn ending stocks stood at [N9].")
    report = vf.verify_citations(st, [], [_call("stocks", 1.62)], handle_prose=True)
    assert report["by_rule"] == {"index_out_of_range": 1} and report["stripped"] == 1
    census = an._drop_slot_orphan_sentences(st, report)
    assert an._fold_ledger_class(report, an._SLOT_ORPHAN_CLASS, census["sentences_dropped"]) == 1
    assert report["by_rule"] == {"index_out_of_range": 1, "slot_orphan": 1}
    assert report["stripped"] == 2 == sum(report["by_rule"].values())
    # the fold is a NO-OP when nothing was deleted, so a clean treatment row's ledger is untouched
    clean = {"enabled": True, "stripped": 4, "by_rule": {"bare_digit": 4}}
    assert an._fold_ledger_class(clean, an._SLOT_ORPHAN_CLASS, 0) == 0
    assert clean == {"enabled": True, "stripped": 4, "by_rule": {"bare_digit": 4}}
    # ...and BOTH serving bodies fold it, in the same position (the one-hop rollback is not a second lane)
    import inspect
    src = inspect.getsource(an)
    assert src.count("_fold_ledger_class(verifier, _SLOT_ORPHAN_CLASS") == 2


def test_the_bare_digit_remedy_mints_its_own_seam_too():
    """FIX Z12, the residual builder-2 recorded rather than fixed: the digit-lint's CHARGE lives in verify
    and mints no seam, so a sentence its REMEDY deleted was invisible to TIDY-2 and its successor could be
    left headless with nothing able to repair it."""
    report = vf._VerifyReport({"enabled": True, "by_rule": {}})
    st = _st("", "Stocks hit 4,250 last week. that is the tightest print in five years.")
    census = an._drop_bare_digit_sentences(st, [], report)
    assert census["sentences_dropped"] == 1
    assert report.strip_seams and report.strip_seams[0]["field"] == "mechanism"
    assert report.strip_seams[0]["key"].startswith("that is the tightest")
    # ...and it is a WHOLE-SENTENCE producer, so its tag is not in the slot-orphan licence set (X2)
    assert report.strip_seams[0]["src"] == an._SEAM_SRC_BARE_DIGIT
    assert an._SEAM_SRC_BARE_DIGIT not in an._SLOT_EMPTYING_SEAM_SRCS


def test_the_two_census_halves_agree_on_the_whole_sentence_kill():
    """FIX Z12. `_resolve_evidence_handles`' docstring claims "the SAME four census keys as
    `number_handles` ... so the two halves of the join read as one instrument" -- and on the identical
    shape they disagreed: the [E] kill charged `handles_dropped` as well as `sentences_dropped`, the [N]
    kill charged only the latter. One census, one rule."""
    e = _st("The ban took effect at [E9].")
    ce = an._resolve_evidence_handles(e, [{"source": "a", "source_key": "k", "date": "2026-01-01",
                                           "text": "x"}], handle_prose=True)
    n = _st("The ban took effect at [N9].")
    cn = an._resolve_number_handles(n, [_call("stocks", 1.62)], handle_prose=True)
    assert e["tldr"] == "" and n["tldr"] == ""
    assert ce["sentences_dropped"] == cn["sentences_dropped"] == 1
    assert ce["handles_dropped"] == cn["handles_dropped"] == 0


def test_the_fold_runs_on_both_serving_bodies_and_only_on_the_treatment():
    """FIX Z1/Z6 AT THE SEAM. `GRAPHRAG_PLANNER=onehop` is a DOCUMENTED rollback lane, so a ledger fold
    on one body only is the same blindness with a flag in front of it -- and the fold is gated on
    `_handles`, or a control row's `by_rule` and `stripped` would move."""
    import pathlib as _pl
    src = _pl.Path(an.__file__).read_text(encoding="utf-8")
    assert src.count("_fold_render_classes(verifier,") == 2          # one call per serving body
    assert src.count("def _fold_render_classes(") == 1               # ...one producer
    for at in (src.index("_fold_render_classes(verifier,"),
               src.rindex("_fold_render_classes(verifier,")):
        assert "_handles" in src[at - 220:at], "the fold is not gated on the treatment"
