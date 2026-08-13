"""D-HP H1 FOLD ROUND 3 -- THE SEAM CARRIER'S PROVENANCE, ITS BLAST RADIUS, AND ITS THIRD PRODUCER.

The Z4/W1 licence made a value-slot sentence deletable only where a strip was RECORDED. The round-2
adversarial verifier then refuted three of that licence's own assertions, each with a reproduction, and
found a fourth producer the remedy did not cover. This file is the pin set for the four fixes:

  X1  `_prune_orphan_evidence_handles` EMPTIES A VALUE SLOT and minted no seam, so the fragment
      "US corn ending stocks stood at." shipped to the reader on the treatment arm. It mints now.
  X2  the seam list was never verifier-only: `_drop_bare_digit_sentences` is a RENDER pass, runs FIRST
      on both bodies and writes the SAME carrier, so ADJACENCY licensed a cut on a terminator-less
      sentence. Every seam now names its PRODUCER and only the SLOT-EMPTYING ones license.
  X3a a seam licenses at most ONE cut (consume on match), so one strip can never drop two sentences.
  X6  an end-of-field strip is a real position: slot-emptying producers mint EMPTY-KEY seams,
      whole-sentence producers keep the skip.

EVERY POSITIVE HERE IS DRIVEN THROUGH THE SERVING BODY'S OWN PASS ORDER (`_serve`, below), not through a
hand-built report -- the coverage hole X1 closes was invisible to every fixture that started from a
`_VerifyReport` someone typed.

H1 FOLD ROUND 4 (2026-08-13) adds the pins for the ONE root cause the round-3 verifier proved was behind
every fragment still reaching the reader: THE SEAM KEY IS A SNAPSHOT OF TEXT LATER PASSES REWRITE.

  Y1  `verify._verify_field` minted its keys ten lines BEFORE its own whitespace cleanup, so in a field
      with two or more strips every key but the last was one character too long and only the FIELD-FINAL
      cue sentence was remedied. It mints from `_strip_cleanup`ed text now.
  Y2  `_tidy_handle_debris` runs BETWEEN the [E] prune's mint and the licence read and rewrites the very
      punctuation the prune emptied. Both sides of the compare are canonicalized (`_licence_canon`).
  Y4  the false-NEGATIVE residual is recorded where the false-positive one already was, and the refuted
      "one sanitize edit ... cannot break an honest match" reassurance is deleted.
  Y5  `_mint_strip_seam` mirrors verify's GRAPHRAG_STRIP_AUDIT projection, so the audit shows ALL
      producers -- with the leak fence (attribute-only when the flag is off) pinned in both directions.

H1 FOLD ROUND 5 (2026-08-13) closes the round-4 verifier's one open major and the minor beside it, and
both are the same edit read from two directions -- THE 40-CHARACTER BOUND WAS ON THE WRONG SIDE:

  W-A  Y5's mirror published render-side keys at the full `_SEAM_LOOKAHEAD` width (measured: 119 chars
       per seam on the estate's own prose) onto `trace['citation_verifier']`, which `/v1/respond`
       returns whole. The cut is now made AT THE PROJECTION (`verify._projected_seam`), for every
       producer, on a COPY -- the in-memory carrier keeps its full width.
  W-B  and the cut at the MINT was itself a false NEGATIVE: it landed at 40 RAW characters BEFORE
       `_licence_canon` deleted characters, so canon could eat into the compared 32 and a real cut went
       unlicensed. Two named reproductions, both driven end to end.
"""
from __future__ import annotations

import inspect
import json

from leviathan.graphrag import answer as an
from leviathan.graphrag import verify as vf


def _ev(i: int = 1) -> list[dict]:
    """One positional evidence row, in the shape `_resolve_evidence_handles` reads."""
    return [{"source": "USDA WASDE", "source_key": "k%d" % i, "date": "2026-01-01",
             "text": "US corn ending stocks were revised.", "ref": "E%d" % i}]


def _serve(structured: dict, uniq: list, calls: list, *, handle_prose: bool = True,
           sources: list | None = None):
    """THE L2 BODY'S HANDLE STACK, IN ITS SHIPPED ORDER (answer.py, the `verifier.get('enabled')` block):
    verify -> bare-digit -> [N] resolve -> class fold -> dedup -> [E] resolve -> wrong-slot -> [E] prune
    -> debris -> slot-orphan -> ledger fold -> TIDY-2.

    Driving the ORDER is the whole point: X1's fragment is produced by a pass that runs BETWEEN the
    verifier and the slot-orphan drop, so no fixture rooted at a hand-built verify report can see it."""
    structured.setdefault("sources", [] if sources is None else sources)
    rep = vf.verify_citations(structured, uniq, calls, handle_prose=handle_prose)
    seen = {"verify_by_rule": dict(rep.get("by_rule") or {}),
            "verify_seams": [dict(s) for s in rep.strip_seams]}
    seen["bare_digit"] = an._drop_bare_digit_sentences(structured, calls, rep)
    nh = an._resolve_number_handles(structured, calls, handle_prose=handle_prose)
    an._fold_render_classes(rep, nh)
    an._dedup_number_handles(structured, calls)
    an._resolve_evidence_handles(structured, uniq, handle_prose=handle_prose)
    seen["pruned"] = an._prune_orphan_evidence_handles(structured, rep)
    an._tidy_handle_debris(structured)
    seen["slot_orphan"] = an._drop_slot_orphan_sentences(structured, rep)
    an._fold_ledger_class(rep, an._SLOT_ORPHAN_CLASS, seen["slot_orphan"].get("sentences_dropped"))
    an._tidy_strip_orphans(structured, rep)
    seen["seams"] = [dict(s) for s in rep.strip_seams]
    return rep, seen


# ══ X1 -- THE THIRD PRODUCER ══════════════════════════════════════════════════════════════════════════

def test_x1_an_E_marker_pruned_out_of_a_value_slot_takes_its_sentence():
    """FIX X1, THE COVERAGE HOLE, DRIVEN END TO END THROUGH THE SERVING ORDER.

    `_prune_orphan_evidence_handles` (CYCLE-10 FIX 3) removes a prose [E] marker the rendered footer
    cannot answer for -- the gate-7 `ab_out_cotton` class, a ref that RESOLVES but whose row the register
    pass deleted. Under handle-only prose that marker IS the figure, so the prune empties a value slot and
    leaves "US corn ending stocks stood at." -- byte-identical to the fragment Z4 exists to remove.
    Before X1 the verifier convicted nothing, minted no seam, and the slot-orphan pass therefore REFUSED
    the cut: `sentences_dropped` 0, and the reader got the fragment. The prune mints its own seam now."""
    st = {"tldr": "US corn ending stocks stood at [E1].", "mechanism": ""}
    _rep, seen = _serve(st, _ev(), [], sources=[])
    # the VERIFIER did nothing at all -- this is not its strip, which is exactly why the hole existed
    assert seen["verify_by_rule"] == {} and seen["verify_seams"] == []
    assert seen["pruned"] == 1                                   # ...the prune is the producer
    assert seen["seams"] == [{"field": "tldr", "key": ".", "src": an._SEAM_SRC_EV_PRUNE}]
    assert seen["slot_orphan"] == {"sentences_dropped": 1}
    assert st["tldr"] == ""                                      # the fragment DIES


def test_x1_the_prune_licenses_only_the_slot_it_actually_emptied():
    """THE POLARITY, on the same producer. A prune that removes a marker from a sentence which does NOT
    end on a value slot opens no orphan, and the sentence it minted a seam for keeps its own text -- the
    seam is a position record, never a deletion order. And a NARROWED group (some members kept) leaves a
    handle standing in the slot, so it empties nothing and mints nothing."""
    st = {"tldr": "Stocks [E1] were revised higher by the agency.", "mechanism": ""}
    _rep, seen = _serve(st, _ev(), [], sources=[])
    assert seen["pruned"] == 1 and seen["slot_orphan"] == {"sentences_dropped": 0}
    assert st["tldr"] == "Stocks were revised higher by the agency."
    # a partial keep: [E1] survives (its row is live), [E2] goes -- the slot still carries a handle
    rep = vf._VerifyReport({"enabled": True, "stripped": 0, "by_rule": {},
                            "resolved": {"E1": {"source": "USDA WASDE", "date": "2026-01-01",
                                                "snippet": "Corn stocks were revised."}}})
    st2 = {"tldr": "US corn ending stocks stood at [E1, E2].",
           "sources": [{"ref": "E1"}, {"ref": "E2"}]}
    assert an._prune_orphan_evidence_handles(st2, rep) == 1
    assert st2["tldr"] == "US corn ending stocks stood at [E1]."
    assert [s for s in rep.strip_seams] == [], "a narrowed group empties no slot, so it mints no seam"


def test_x1_the_mint_is_on_both_serving_bodies():
    """`GRAPHRAG_PLANNER=onehop` is a DOCUMENTED rollback. A remedy that only covers the L2 body is the
    same defect with a flag in front of it, so the prune is called identically on both -- and the mint
    lives INSIDE the prune, which is what makes one call site enough per body."""
    src = inspect.getsource(an)
    assert src.count("_prune_orphan_evidence_handles(structured, verifier, market_register=_mr)") == 2
    assert src.count("src=_SEAM_SRC_EV_PRUNE") == 1               # one mint, inside the shared function


# ══ X6 -- THE EMPTY-KEY DECISION ══════════════════════════════════════════════════════════════════════

def test_x6_a_field_final_prune_mints_an_empty_key_seam_and_the_fragment_dies():
    """FIX X6, THE ASYMMETRY RESOLVED AND PINNED. A strip applied at the very END of a field leaves no
    successor text, so the seam's key is "". `verify` always minted that record; `answer._mint_strip_seam`
    always skipped it. THE DECISION: an end-of-field cut is a REAL POSITION and a real emptied slot, so
    SLOT-EMPTYING producers mint it (this test) and WHOLE-SENTENCE producers keep the skip (the test
    below) -- an empty key can never TIDY-2-join to an orphan line, which is all their seams are for."""
    st = {"tldr": "US corn ending stocks stood at [E1]", "mechanism": ""}
    _rep, seen = _serve(st, _ev(), [], sources=[])
    assert seen["seams"] == [{"field": "tldr", "key": "", "src": an._SEAM_SRC_EV_PRUNE}]
    assert seen["slot_orphan"] == {"sentences_dropped": 1} and st["tldr"] == ""
    # verify's own field-final strip mints the same empty key -- the two producers now agree
    st2 = {"tldr": "US corn ending stocks stood at [N9]", "mechanism": "", "sources": []}
    rep2 = vf.verify_citations(st2, [], [], handle_prose=True)
    assert [dict(s) for s in rep2.strip_seams] == [{"field": "tldr", "key": "", "src": "verify"}]
    assert an._drop_slot_orphan_sentences(st2, rep2) == {"sentences_dropped": 1}


def test_x6_a_whole_sentence_producer_keeps_the_empty_key_skip():
    """THE OTHER HALF OF THE DECISION. `_drop_bare_digit_sentences` deleting the LAST sentence of a field
    has no successor text to record; the seam would be a licence-shaped record standing for nothing, and
    TIDY-2 could not use it. It is not minted."""
    rep = vf._VerifyReport({"enabled": True, "by_rule": {}})
    st = {"tldr": "", "mechanism": "Stocks hit 4,250 last week."}
    assert an._drop_bare_digit_sentences(st, [], rep)["sentences_dropped"] == 1
    assert st["mechanism"] == "" and rep.strip_seams == []
    # ...and the same call with a successor DOES mint (the skip is about the empty key, not the producer)
    st = {"tldr": "", "mechanism": "Stocks hit 4,250 last week. that print stands."}
    assert an._drop_bare_digit_sentences(st, [], rep)["sentences_dropped"] == 1
    assert [s["src"] for s in rep.strip_seams] == [an._SEAM_SRC_BARE_DIGIT]


# ══ X2 -- THE PRODUCER TAG ════════════════════════════════════════════════════════════════════════════

def test_x2_a_bare_digit_deletion_does_not_license_its_neighbour():
    """FIX X2, THE VERIFIER'S REPRODUCTION, PINNED.

    The claim W1 shipped was "the licence is the VERIFIER'S OWN recorded drop records". It was false:
    `_drop_bare_digit_sentences` runs FIRST in the handle stack on both bodies and mints into the SAME
    carrier, and `_drop_slot_orphan_sentences` snapshots that carrier AFTERWARDS.

    THE SHAPE THAT BROKE IT is a newline-bounded sentence, which has no terminator: the digit-lint deletes
    line 2 and mints a seam whose key is line 3's text, and line 1 -- a complete, fully backed sentence the
    verifier never touched -- normalizes to that same key and was deleted off it. ADJACENCY became a
    licence, which this pass's own pin docstring explicitly denies.

    THE FIX IS PROVENANCE. `bare_digit` is a WHOLE-SENTENCE producer: nothing survives with an emptied
    slot, so its seams are TIDY-2 material and are not in `_SLOT_EMPTYING_SEAM_SRCS`."""
    mech = ("- No high-confidence price-supportive driver is documented as active at this as-of\n"
            "- Stocks rose 12.5 percent on the week.\n"
            "- Exports held firm across the period.")
    st = {"tldr": "", "mechanism": mech, "sources": []}
    rep = vf.verify_citations(st, [], [], handle_prose=True)
    assert rep.strip_seams == [], "verify only CHARGES a bare digit; it strips nothing here"
    assert rep["by_rule"] == {"bare_digit": 1}
    assert an._drop_bare_digit_sentences(st, [], rep)["sentences_dropped"] == 1      # line 2 goes
    assert [s["src"] for s in rep.strip_seams] == [an._SEAM_SRC_BARE_DIGIT]
    assert an._drop_slot_orphan_sentences(st, rep) == {"sentences_dropped": 0}
    assert "No high-confidence price-supportive driver" in st["mechanism"]           # LINE 1 SURVIVES
    assert "Exports held firm across the period." in st["mechanism"]
    assert "Stocks rose 12.5 percent" not in st["mechanism"]


def test_x2_the_licence_set_is_the_slot_emptying_producers_and_the_tag_fails_closed():
    """THE TAG TEST ITSELF, on the one fixture, all four producers plus the untagged case.

    A seam with no `src` -- a legacy record, a hand-built fixture, a producer added without reading this
    file -- is REFUSED. A record no consumer can classify does not get to delete a reader's sentence."""
    assert an._SLOT_EMPTYING_SEAM_SRCS == frozenset({"verify", "ev_prune"})
    for src in (an._SEAM_SRC_VERIFY, an._SEAM_SRC_EV_PRUNE):
        assert an._slot_orphan_licensed([{"field": "tldr", "key": ".", "src": src}], "tldr", ".") is True
    for src in (an._SEAM_SRC_BARE_DIGIT, an._SEAM_SRC_SLOT_ORPHAN, "", "some_future_pass"):
        assert an._slot_orphan_licensed([{"field": "tldr", "key": ".", "src": src}], "tldr", ".") is False
    assert an._slot_orphan_licensed([{"field": "tldr", "key": "."}], "tldr", ".") is False


def test_x2_tidy_2_still_accepts_every_producer_tag():
    """THE NARROWING IS THE LICENCE'S ALONE. `_seam_adjacent` answers a DIFFERENT question -- "did
    something get removed just before this orphan line" -- and every producer answers it, so TIDY-2's join
    is unchanged by the tag and still repairs a seam any of the four opened (including an untagged legacy
    record, which the shipped fixtures use)."""
    frag = " that left the balance sheet tight and the basis firm."
    for src in ("verify", "bare_digit", "ev_prune", "slot_orphan"):
        assert an._seam_adjacent([{"field": "mechanism", "key": vf._seam_key(frag), "src": src}],
                                 "mechanism", frag) is True
    assert an._seam_adjacent([{"field": "mechanism", "after": frag}], "mechanism", frag) is True


# ══ X3a -- ONE SEAM, ONE CUT ══════════════════════════════════════════════════════════════════════════

def test_x3a_one_strip_can_never_drop_two_sentences():
    """FIX X3a, THE VERIFIER'S SECOND REPRODUCTION, BOUNDED.

    The join is a normalized PREFIX compare (32 cap, 8 floor over `min(len(key), len(tail))`), so two cut
    positions in one field whose successors agree over the compared window license each other. Here ONE
    strip on a field carrying a repeated short sentence licensed TWO deletions -- and the second sentence
    was one nothing had ever touched.

    A MATCHED SEAM IS NOW CONSUMED, so N recorded cuts license at most N deletions. The sentence that
    dies is the one at the strip; the innocent repeat survives."""
    st = {"tldr": "", "sources": [],
          "mechanism": "Prices settled near [E9]. Trade was thin. Prices settled near. Trade was thin."}
    rep = vf.verify_citations(st, [], [], handle_prose=True)
    assert len(rep.strip_seams) == 1 and rep["stripped"] == 1
    assert st["mechanism"].startswith("Prices settled near. Trade was thin.")
    assert an._drop_slot_orphan_sentences(st, rep) == {"sentences_dropped": 1}
    assert st["mechanism"] == "Trade was thin. Prices settled near. Trade was thin."
    # TWO strips still license TWO cuts -- the bound is the strip count, not a cap of one
    st2 = {"tldr": "", "sources": [],
           "mechanism": "Prices settled near [E9]. Trade was thin. Prices settled near [E9]. "
                        "Trade was thin."}
    rep2 = vf.verify_citations(st2, [], [], handle_prose=True)
    assert len(rep2.strip_seams) == 2
    assert an._drop_slot_orphan_sentences(st2, rep2) == {"sentences_dropped": 2}
    assert st2["mechanism"] == "Trade was thin. Trade was thin."


def test_x3a_consumption_never_shortens_the_report_itself():
    """THE CONSUMPTION IS OFF THE PASS'S OWN SNAPSHOT. `_report_seams` copies in BOTH branches, so a
    reader can never shorten the carrier TIDY-2 (which runs after this pass) is about to join on."""
    st = {"tldr": "US corn ending stocks stood at [N9].", "mechanism": "", "sources": []}
    rep = vf.verify_citations(st, [], [], handle_prose=True)
    before = [dict(s) for s in rep.strip_seams]
    assert before and an._drop_slot_orphan_sentences(st, rep)["sentences_dropped"] == 1
    assert [dict(s) for s in rep.strip_seams][:len(before)] == before
    # the audited/dict branch is a copy too (it is the same list object on the report otherwise)
    d = {"strip_seams": [{"field": "tldr", "key": ".", "src": "verify"}]}
    got = an._report_seams(d)
    got.pop()
    assert d["strip_seams"] == [{"field": "tldr", "key": ".", "src": "verify"}]


# ══ X3b -- THE CLAIM, CORRECTED WHERE IT IS WRITTEN ═══════════════════════════════════════════════════

def test_x3b_the_code_no_longer_claims_positional_exactness():
    """FIX X3b. The comment block around the licence asserted "nowhere else in the field can carry the
    same successor text" and `_slot_orphan_licensed`'s docstring asserted "only one position in a field
    can have that successor text". Both are FALSE of a bounded-prefix text join, and the verifier refuted
    them with a 32-char and a 17-char reproduction.

    The residual is ACCEPTED (measured corpus exposure zero across 32,557 stored sentences, bounded by
    X3a, G2's fluency read as the runtime guard) and RECORDED -- but it may not be described as a
    guarantee the code does not provide. This pin is on the WORDING, because the wording is what a later
    wave will widen the compare against."""
    src = inspect.getsource(an)
    for claim in ("nowhere else in the field can carry the same successor text",
                  "only one position in a field can have that successor text"):
        assert claim not in src, claim
    doc = an._slot_orphan_licensed.__doc__ or ""
    assert "not positionally exact" in inspect.getsource(an._drop_slot_orphan_sentences).lower() \
        or "IT IS A TEXT JOIN, NOT A POSITION." in doc
    assert "X3b" in doc or "X3b" in src


def test_x3b_the_collision_is_real_and_is_bounded_not_denied():
    """THE RESIDUAL, PINNED AS A BEHAVIOUR so a later reader finds it as a measured fact rather than as a
    surprise. A 17-char shared successor is enough for a foreign position to license, and the guard that
    keeps it survivable is X3a's one-shot rule -- NOT positional exactness."""
    seams = [{"field": "mechanism", "key": vf._seam_key(". Trade was thin."), "src": "verify"}]
    # a DIFFERENT position whose successor text is identical still joins -- that is the residual
    assert an._slot_orphan_licensed(seams, "mechanism", ". Trade was thin.") is True
    assert seams == [], "...and it was consumed, so it cannot license a second one"


# ══ H1 FOLD ROUND 4 ═══════════════════════════════════════════════════════════════════════════════════
# Y1 -- THE KEY IS MINTED FROM THE TEXT THE PRODUCER RETURNS
#
# The two round-4 fixes overlap ON PURPOSE (Y2's canon also erases whitespace in front of a terminator,
# which is the class Y1's cleanup closes), so the Y1 pins are stated at the PRODUCER'S OUTPUT -- the
# recorded key itself -- and the behaviour pins below stand on both. That is what keeps each fix's
# mutant reddening its own pins instead of hiding behind the other.

def test_y1_the_recorded_key_is_the_string_the_renderer_will_read():
    """FIX Y1 AT THE PRODUCER. `_verify_field` returns `_strip_cleanup(text)`; a strip that empties a slot
    in front of a "."/","/";" leaves the " ." that cleanup closes. Minting BEFORE it recorded a key one
    character longer -- at every cut but the field-final one, whose window carries no later cut -- so the
    prefix compare failed inside its own 32-char window. The keys below are the post-cleanup strings."""
    st = {"tldr": "Stocks stood at [N9]. Exports totalled at [N8].", "mechanism": "", "sources": []}
    rep = vf.verify_citations(st, [], [], handle_prose=True)
    assert [s["key"] for s in rep.strip_seams] == [". exports totalled at.", "."]
    assert st["tldr"] == "Stocks stood at. Exports totalled at."      # ...and the return agrees
    # three strips: every earlier key spans the later cuts, so every earlier key was stale
    st3 = {"tldr": "", "sources": [],
           "mechanism": "Stocks stood at [N9]. Exports totalled at [N8]. Crush ran at [N7]."}
    rep3 = vf.verify_citations(st3, [], [], handle_prose=True)
    assert [s["key"] for s in rep3.strip_seams] == [
        ". exports totalled at. crush ran at.", ". crush ran at.", "."]
    # the comma spelling and the [E] namespace mint the same way
    st4 = {"tldr": "Stocks stood at [E9], and exports totalled at [E8].", "mechanism": "", "sources": []}
    rep4 = vf.verify_citations(st4, [], [], handle_prose=True)
    assert [s["key"] for s in rep4.strip_seams] == [", and exports totalled at.", "."]


def test_y1_the_cleanup_is_window_local_and_that_is_sound():
    """WHY THE WINDOW RATHER THAN THE RETURN VALUE (no offset arithmetic, provably the same compare).
    `_strip_cleanup` only ever deletes SPACES and never crosses a newline, so a match straddling the
    window's left edge deletes characters the key would strip anyway, and one straddling the right edge
    lands past the 32 NORMALIZED characters the licence compares."""
    assert vf._strip_cleanup("a  b .") == "a b."
    assert vf._strip_cleanup(vf._strip_cleanup("a  b .")) == vf._strip_cleanup("a  b .")  # idempotent
    assert vf._strip_cleanup("a  \n  b") == "a \n b"        # collapses per line; the newline stands
    for sample in ("a  b .", "  ;x  ,", "one  \n  two ;", "()  -- ."):
        out = vf._strip_cleanup(sample)
        assert out.count("\n") == sample.count("\n")
        assert out.replace(" ", "") == sample.replace(" ", "")   # ONLY spaces are ever deleted
    text = "stood at. " + "the very long successor sentence that follows the cut " * 4
    for pos in (0, 5, 9):                                   # windowed vs whole, at three offsets
        win = vf._seam_key(vf._strip_cleanup(text[pos:pos + vf._SEAM_LOOKAHEAD]))
        whole = vf._seam_key(vf._strip_cleanup(text)[pos:pos + vf._SEAM_LOOKAHEAD])
        assert win[:32] == whole[:32], pos                  # the only 32 characters the licence reads


def test_y1_two_strips_now_drop_two_cue_sentences():
    """THE COMPOUND ARM THE ROUND-3 VERIFIER NAMED, DRIVEN THROUGH THE SERVING ORDER. Pre-fix: 2 strips
    dropped 1 and the reader got "Stocks stood at."; 3 strips shipped 2 fragments; 4 cue sentences shipped
    3. Both handle namespaces and both prose fields."""
    for ns in ("N", "E"):
        st = {"tldr": "Stocks stood at [%s9]. Exports totalled at [%s8]." % (ns, ns), "mechanism": ""}
        _rep, seen = _serve(st, [], [], sources=[])
        assert seen["slot_orphan"] == {"sentences_dropped": 2}, ns
        assert st["tldr"] == "", ns
    st3 = {"tldr": "Stocks stood at [N9]. Exports totalled at [N8]. Crush ran at [N7].", "mechanism": ""}
    _rep, seen = _serve(st3, [], [], sources=[])
    assert seen["slot_orphan"] == {"sentences_dropped": 3} and st3["tldr"] == ""
    st4 = {"tldr": "", "mechanism": "Stocks stood at [N9]. Exports totalled at [N8]. Crush ran at [N7]. "
                                    "Basis sat at [N6]."}
    _rep, seen = _serve(st4, [], [], sources=[])
    assert seen["slot_orphan"] == {"sentences_dropped": 4} and st4["mechanism"] == ""
    # the comma spelling is ONE sentence and dies whole
    stc = {"tldr": "Stocks stood at [N9], and exports totalled at [N8].", "mechanism": ""}
    _rep, seen = _serve(stc, [], [], sources=[])
    assert seen["slot_orphan"] == {"sentences_dropped": 1} and stc["tldr"] == ""


def test_y1_the_estate_reproduction_kills_both_neighbours():
    """THE SHAPE THE VERIFIER FOUND ON THE ESTATE'S OWN STORED PROSE (the
    `tier_20260812T051533Z.json` mechanism). Pre-fix the SECOND fragment died -- its key had no later cut
    in it -- while the FIRST shipped, and that asymmetry inside one field was the whole tell. Both die."""
    st = {"tldr": "", "mechanism": "In MY2023 it was [N9]; by MY2024 it had tightened to [N8]; the "
                                   "MY2025 carryout is thinner still."}
    _rep, seen = _serve(st, [], [], sources=[])
    assert seen["slot_orphan"] == {"sentences_dropped": 2}
    assert st["mechanism"] == "the MY2025 carryout is thinner still."
    assert "In MY2023 it was" not in st["mechanism"]


# ══ Y2 -- THE COMPARE HAPPENS IN DEBRIS-FREE SPACE ════════════════════════════════════════════════════

_DEBRIS_SHAPES = (
    ("emptied paren", "US corn ending stocks stood at (%s)."),
    ("emptied bracket", "US corn ending stocks stood at [%s]."),
    ("spaced paren", "US corn ending stocks were revised to ( %s )."),
    ("dash before terminator", "US corn ending stocks stood at %s --."),
)


def test_y2_the_debris_pass_can_no_longer_invalidate_the_prune_s_seam():
    """FIX Y2, THE EV_PRUNE PRODUCER, ALL FOUR AT-THE-CUT SHAPES, DRIVEN THROUGH THE SERVING ORDER.
    `_tidy_handle_debris` runs between the mint and the read and rewrites exactly the punctuation the
    prune emptied, so pre-fix each of these shipped "US corn ending stocks stood at." to the reader."""
    for label, shape in _DEBRIS_SHAPES:
        st = {"tldr": shape % "[E1]", "mechanism": ""}
        _rep, seen = _serve(st, _ev(), [], sources=[])
        assert seen["pruned"] == 1, label
        assert [s["src"] for s in seen["seams"]] == [an._SEAM_SRC_EV_PRUNE], label
        assert seen["slot_orphan"] == {"sentences_dropped": 1}, label
        assert st["tldr"] == "", label


def test_y2_the_same_shapes_under_the_verify_producer_and_both_namespaces():
    """NOT SPECIFIC TO THE NEW PRODUCER, which is why the fix is at the consumer. The identical refusal
    fired for `verify`'s own positional strip, in the [N] namespace and in the [E] one."""
    for label, shape in _DEBRIS_SHAPES:
        for ns in ("[N9]", "[E9]"):
            st = {"tldr": shape % ns, "mechanism": ""}
            _rep, seen = _serve(st, [], [], sources=[])
            assert [s["src"] for s in seen["seams"]] == ["verify"], (label, ns)
            assert seen["slot_orphan"] == {"sentences_dropped": 1}, (label, ns)
            assert st["tldr"] == "", (label, ns)


def test_y2_licence_canon_erases_the_debris_classes_and_nothing_else():
    """THE CANON ITSELF: `_seam_key`'s normalization plus the punctuation classes `_DEBRIS_RULES`
    rewrites -- bracket/paren frames, dash runs, the emptied list separator, whitespace pulled off a
    terminator. WORDS ARE NEVER TOUCHED, so the join still reads prose."""
    assert an._licence_canon(").") == "." and an._licence_canon("].") == "."
    assert an._licence_canon("--.") == "." and an._licence_canon(" ( ) .") == "."
    assert an._licence_canon("fell,.") == "fell." and an._licence_canon(". Exports at .") == ". exports at."
    assert an._licence_canon("stocks stood at.") == "stocks stood at."
    assert an._licence_canon(an._licence_canon("( -- ) .")) == an._licence_canon("( -- ) .")


def test_y2_tidy_2_keeps_the_plain_seam_key_join():
    """THE WIDENING IS THE LICENCE'S ALONE. TIDY-2 joins a whole ORPHAN LINE against a seam minted in the
    same pass order and has no stale-key problem to solve, so `_seam_adjacent` is untouched."""
    src = inspect.getsource(an._seam_adjacent)
    assert "_licence_canon" not in src and "_seam_key" in src
    frag = " that left the balance sheet tight and the basis firm."
    assert an._seam_adjacent([{"field": "mechanism", "key": vf._seam_key(frag), "src": "verify"}],
                             "mechanism", frag) is True


def test_y2_a_mid_sentence_cut_is_a_recorded_non_licence():
    """WHAT THE CANON DOES NOT REACH, PINNED SO IT IS FOUND AS A DECISION RATHER THAN AS A SURPRISE.
    "A dash -- [E1] -- stood at." is pruned MID-sentence: the seam sits before "-- stood at.", not at the
    sentence's own end, and canon converges residue AT a cut -- it cannot move a cut. The sentence's core
    ends on a value cue BEFORE the strip as well as after, so the corpus oracle does not count it as a Z4
    fragment either. It is refused, on both producers."""
    st = {"tldr": "US corn ending stocks -- [E1] -- stood at.", "mechanism": ""}
    _rep, seen = _serve(st, _ev(), [], sources=[])
    assert seen["pruned"] == 1 and [s["src"] for s in seen["seams"]] == [an._SEAM_SRC_EV_PRUNE]
    assert seen["slot_orphan"] == {"sentences_dropped": 0}
    assert st["tldr"] == "US corn ending stocks -- stood at."
    st2 = {"tldr": "A dash -- [N9] -- stood at.", "mechanism": ""}
    _rep2, seen2 = _serve(st2, [], [], sources=[])
    assert seen2["slot_orphan"] == {"sentences_dropped": 0} and st2["tldr"] == "A dash -- stood at."


# ══ Y4 -- THE FALSE-NEGATIVE RESIDUAL, RECORDED WHERE THE FALSE-POSITIVE ONE ALREADY WAS ══════════════

def test_y4_the_refuted_reassurance_is_deleted_and_the_second_direction_is_stated():
    """FIX Y4. X3b's honesty correction was ONE-SIDED: it recorded the collision the licence can cause
    (wrong sentence dies) and was silent on the refusal it could not avoid (right sentence lives), which
    was the bigger measured number. The docstring actively understated it -- "one sanitize edit deep
    inside the successor cannot break an honest match" -- and the edits that broke honest matches were
    neither deep nor sanitize's. This pin is on the WORDING, because the wording is what the next wave
    will widen the compare against."""
    src = inspect.getsource(an)
    assert "cannot break an honest match" not in src, "the refuted reassurance must not come back"
    doc = an._slot_orphan_licensed.__doc__ or ""
    assert "FALSE-NEGATIVE RESIDUAL" in doc
    for token in ("Y1", "Y2", "59", "45", "14"):            # the two rewriters and the pre-fix oracle
        assert token in doc, token
    block = inspect.getsource(an._drop_slot_orphan_sentences)
    assert "SNAPSHOT OF TEXT LATER PASSES REWRITE" in src and "X3b, THE OTHER DIRECTION" in src
    assert "not positionally exact" in block.lower() or "IT IS A TEXT JOIN, NOT A POSITION." in doc


# ══ Y5 -- THE AUDIT PROJECTION SHOWS EVERY PRODUCER, AND THE LEAK FENCE IS THE FLAG ═══════════════════

def test_y5_the_strip_audit_projection_mirrors_every_producer(monkeypatch):
    """FIX Y5 (observability). `verify` appends each seam to the internal carrier AND -- under
    GRAPHRAG_STRIP_AUDIT -- to the serializable projection; `_mint_strip_seam` wrote the attribute only,
    so the one debug surface for seams was blind to X1's new producer and to X2's new tags BY
    CONSTRUCTION. It mirrors the projection now, under the same flag read the same way."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    st = {"tldr": "US corn ending stocks stood at [E1].", "mechanism": ""}
    rep, _seen = _serve(st, _ev(), [], sources=[])
    proj = rep.get("strip_seams") or []
    assert [s["src"] for s in proj] == [an._SEAM_SRC_EV_PRUNE]
    # SAME CONTENT, DIFFERENT OBJECT (round-5 W-A): the projection is a CUT COPY, so on a key that is
    # already short the two agree value-for-value while never being the same dict. See the W-A pins.
    assert [dict(s) for s in proj] == [dict(s) for s in rep.strip_seams]
    assert all(p is not c for p, c in zip(proj, rep.strip_seams))
    assert set(proj[0]) == {"field", "key", "src"}          # the record shape verify already publishes
    # a whole-sentence producer projects too -- the audit's job is to show ALL of them
    rep2 = vf._VerifyReport({"enabled": True, "by_rule": {}})
    rep2.strip_seams = []
    st2 = {"tldr": "", "mechanism": "Stocks hit 4,250 last week. that print stands."}
    an._drop_bare_digit_sentences(st2, [], rep2)
    assert [s["src"] for s in rep2.get("strip_seams")] == [an._SEAM_SRC_BARE_DIGIT]


def test_y5_with_the_audit_off_the_mint_writes_no_serializable_byte(monkeypatch):
    """THE LEAK FENCE, PINNED IN THE OTHER DIRECTION. The seams ride an attribute no serializer can see;
    the projection is a DEBUG surface and the flag is the whole containment. With the audit off, the
    report dict is byte-identical to a run that minted nothing."""
    monkeypatch.delenv("GRAPHRAG_STRIP_AUDIT", raising=False)
    st = {"tldr": "US corn ending stocks stood at [E1].", "mechanism": ""}
    rep, _seen = _serve(st, _ev(), [], sources=[])
    assert rep.strip_seams and rep.strip_seams[0]["src"] == an._SEAM_SRC_EV_PRUNE
    assert "strip_seams" not in dict(rep)
    assert "strip_seams" not in json.dumps(rep)
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "off")       # the explicit off spelling reads the same
    rep2 = vf._VerifyReport({"enabled": True, "by_rule": {}})
    rep2.strip_seams = []
    an._mint_strip_seam(rep2, "tldr", ".", src=an._SEAM_SRC_EV_PRUNE)
    assert len(rep2.strip_seams) == 1 and "strip_seams" not in dict(rep2)


# ══ W-A -- THE 40-CHAR BOUND LIVES AT THE PROJECTION; THE CARRIER KEEPS ITS FULL WIDTH ════════════════

# THE ESTATE'S OWN STORED PROSE, QUOTED. This is the `mechanism` paragraph of
# `data/dmw_p4/tier_20260812T051533Z.json` (per_answer[0]) that the round-4 verifier measured the
# 119-character projected keys on. It is INLINED rather than read from the file so the pin is hermetic --
# that artifact is an untracked local capture, and a bound this load-bearing may not depend on one. Driven
# 2026-08-13: the inlined text reproduces the artifact's own numbers exactly (two `slot_orphan` carrier
# keys of 119 chars, two `sentences_dropped`, the same surviving sentence). The em-dash is spelled
# `chr(0x2014)` to keep this source ASCII (the same rule verify.py's `_QUOTE_EDGE` follows); it is U+2014
# in the stored prose, which is 85% of this estate's dashes -- see 10.12-R5's em-dash census.
_ESTATE_MECHANISM = (
    "The watch-list for that tipping point is the US stocks-to-use ratio for meal. "
    "In MY2023 it was [N16]; by MY2024 it had tightened to [N17]; the MY2025 projection "
    "stands at [N18] " + chr(0x2014) + " still a razor-thin buffer, which means a supply "
    "disruption at this "
    "level hits a balance sheet with little cushion and a non-linear price response is more "
    "likely than in a well-stocked environment.")


def test_wa_the_projection_is_cut_to_40_for_every_producer_and_the_carrier_is_not(monkeypatch):
    """FIX W-A, THE ROUND-4 VERIFIER'S OPEN MAJOR, DRIVEN ON THE REAL ESTATE PROSE IT WAS MEASURED ON.

    `verify._seam_key` used to cut at `_SEAM_KEY_CHARS` and `answer._seam_key` never did, so once Y5
    mirrored the audit projection the render-side producers published keys bounded only by
    `_SEAM_LOOKAHEAD` = 120 -- MEASURED AT 119 CHARACTERS PER SEAM here -- i.e. up to 120 characters of
    PRE-SANITIZE prose per seam on `trace['citation_verifier']`, which `/v1/respond` returns whole, under
    a flag the repo's config-of-record says is live in serving. That is three times the class FIX-CYCLE-2
    review major 7 bounded, on the exact channel it bounded it for.

    THE BOUND IS AT THE PROJECTION SITE, NOT AT THE MINT, and both halves are pinned here: EVERY projected
    key is <= 40 for EVERY producer, and the in-memory carrier on the SAME run keeps its full width
    (capping the carrier instead would import the W-B false negative into the licence path)."""
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    st = {"tldr": "", "mechanism": _ESTATE_MECHANISM}
    rep, seen = _serve(st, [], [], sources=[])
    car, proj = list(rep.strip_seams), list(rep.get("strip_seams") or [])
    assert seen["slot_orphan"] == {"sentences_dropped": 2}   # the estate's own disposition, unchanged
    assert len(proj) == len(car) >= 5 and {s["src"] for s in car} == {"verify", "slot_orphan"}
    # (a) THE PROJECTION: every key, every producer, cut to the published class
    assert all(len(s["key"]) <= vf._SEAM_KEY_CHARS for s in proj), [len(s["key"]) for s in proj]
    assert max(len(s["key"]) for s in proj) == vf._SEAM_KEY_CHARS == 40
    # (b) THE CARRIER on the same run: the 119-char keys the verifier measured, NOT cut
    wide = [s for s in car if s["src"] == an._SEAM_SRC_SLOT_ORPHAN]
    assert [len(s["key"]) for s in wide] == [119, 119], [len(s["key"]) for s in wide]
    assert all(len(s["key"]) > vf._SEAM_KEY_CHARS for s in car)
    assert wide[0]["key"].startswith("by my2024 it had tightened to; the my2025 projection stands at")
    # (c) and the projected copy of that same seam is exactly its own first 40 characters
    pw = [s for s in proj if s["src"] == an._SEAM_SRC_SLOT_ORPHAN]
    assert [len(s["key"]) for s in pw] == [40, 40]
    assert [s["key"] for s in pw] == [s["key"][:40] for s in wide]
    # the prose past character 40 does not reach the projection at all, on any producer's key
    assert "supply disruption" not in json.dumps(proj)
    assert "supply disrup" in wide[0]["key"]                 # ...while the licence still has it


def test_wa_the_projection_is_a_copy_and_the_helper_is_the_one_site(monkeypatch):
    """THE MECHANISM, PINNED SO A LATER PASS CANNOT RE-UNIFY THE TWO SIDES. Round 4 appended the SAME dict
    object to the carrier and to the projection, which is exactly why one number had to serve two
    incompatible requirements. `verify._projected_seam` is the single cut site and it returns a COPY;
    `answer._mint_strip_seam` calls it rather than spelling the slice itself."""
    long = "x" * 200
    assert len(vf._seam_key(long)) == 200                    # the MINT is not bounded (W-B)
    assert len(an._seam_key(long)) == 200                    # ...and the two normalizations still agree
    assert vf._seam_key(long) == an._seam_key(long)
    seam = {"field": "tldr", "key": long, "src": "verify"}
    cut = vf._projected_seam(seam)
    assert cut is not seam and seam["key"] == long           # the source record is untouched
    assert len(cut["key"]) == 40 and set(cut) == {"field", "key", "src"}
    assert "[:" not in inspect.getsource(vf._seam_key).rsplit('"""', 1)[-1]   # no cut in the CODE
    assert "_projected_seam" in inspect.getsource(an._mint_strip_seam)
    # the render-side mint projects through the helper, on a key far past the bound
    monkeypatch.setenv("GRAPHRAG_STRIP_AUDIT", "on")
    rep = vf._VerifyReport({"enabled": True, "by_rule": {}})
    rep.strip_seams = []
    an._mint_strip_seam(rep, "tldr", long, src=an._SEAM_SRC_EV_PRUNE)
    assert len(rep.strip_seams[0]["key"]) == 120             # _SEAM_LOOKAHEAD, the mint's own bound
    assert len(rep["strip_seams"][0]["key"]) == 40
    assert rep["strip_seams"][0] is not rep.strip_seams[0]


def test_wa_with_the_audit_off_the_estate_field_writes_no_serializable_byte(monkeypatch):
    """THE OFF-DIRECTION FENCE, RE-PINNED ON THE WIDE CASE. The flag is still the whole containment: on
    the very field that projects 119-character keys with the audit on, the report dict with it off is
    byte-identical to a run that minted nothing."""
    monkeypatch.delenv("GRAPHRAG_STRIP_AUDIT", raising=False)
    st = {"tldr": "", "mechanism": _ESTATE_MECHANISM}
    rep, _seen = _serve(st, [], [], sources=[])
    assert rep.strip_seams and max(len(s["key"]) for s in rep.strip_seams) > vf._SEAM_KEY_CHARS
    assert "strip_seams" not in dict(rep)
    blob = json.dumps(rep)
    assert "strip_seams" not in blob and "razor-thin" not in blob


# ══ W-B -- THE CAP IS OFF THE MINT, SO CANON CANNOT EAT INTO THE COMPARED 32 ══════════════════════════

def test_wb_a_dash_run_split_by_the_40_char_cap_no_longer_refuses_a_real_cut():
    """FIX W-B, THE ROUND-4 VERIFIER'S FIRST NAMED REPRODUCTION, DRIVEN END TO END THROUGH THE SERVING
    ORDER. The fold's own root cause survived at a third site: the key was cut at 40 RAW characters
    BEFORE `_licence_canon` DELETED characters from it, so the two 32-character compare windows covered
    different source spans. Here the cut split a `--` run and left a lone `-` that `-{2,}` cannot erase;
    the canon'd key ran to 33 characters against a 32-character tail canon and diverged at index 31.
    PRE-FIX: `sentences_dropped` 0 and the reader got "The December contract were. The December contract
    sits at --." POST-FIX the licensed sentence dies."""
    st = {"tldr": "The December contract were ( [E9] ) --.  "
                  "The December contract sits at -- [E4] --.", "mechanism": ""}
    rep, seen = _serve(st, [], [], sources=[])
    keys = [s["key"] for s in rep.strip_seams]
    assert keys[0] == ") --. the december contract sits at -- --."     # 42 chars: the run is INTACT
    assert len(keys[0]) > vf._SEAM_KEY_CHARS
    assert an._licence_canon(keys[0]) == ". the december contract sits at."    # ...and canons to 32
    assert seen["slot_orphan"] == {"sentences_dropped": 1}
    assert "The December contract were" not in st["tldr"]
    assert st["tldr"] == "The December contract sits at --."


def test_wb_the_second_reproduction_dies_the_same_way():
    """THE VERIFIER'S SECOND NAMED REPRODUCTION, same class, three sentences and both namespaces. Pre-fix
    `sentences_dropped` 0 and "Brazilian output were." shipped."""
    st = {"tldr": "Brazilian output were [E8],.  Exports hit -- [E8] --.  "
                  "Exports reads -- [N6] --.", "mechanism": ""}
    rep, seen = _serve(st, [], [], sources=[])
    assert len(rep.strip_seams[0]["key"]) > vf._SEAM_KEY_CHARS
    assert seen["slot_orphan"] == {"sentences_dropped": 1}
    assert "Brazilian output were" not in st["tldr"]
    assert st["tldr"] == "Exports hit --. Exports reads --."


def test_wb_the_bound_is_not_reintroduced_at_either_mint():
    """THE GUARD ON THE FIX ITSELF. Neither normalization may carry a length cut -- the bound belongs to
    `_projected_seam`. Pinned on the SOURCE as well as on the behaviour, because the failure mode is a
    one-token edit that no short-key fixture can see."""
    for fn in (vf._seam_key, an._seam_key):
        body = inspect.getsource(fn).rsplit('"""', 1)[-1]    # the CODE, past its own docstring
        assert "_SEAM_KEY_CHARS" not in body and "[:" not in body, fn.__name__
        assert len(fn("y" * 90)) == 90, fn.__name__
    assert "_SEAM_KEY_CHARS" in inspect.getsource(vf._projected_seam)
    # and the two consumers that read the carrier still see the full width
    wide = "the " + "long successor clause " * 6
    seams = [{"field": "tldr", "key": vf._seam_key(wide), "src": "verify"}]
    assert len(seams[0]["key"]) > 40
    assert an._seam_adjacent(list(seams), "tldr", wide) is True
    assert an._slot_orphan_licensed(list(seams), "tldr", wide) is True
