"""D-HP-6 -- THE HANDLE-GRAMMAR CONFORMANCE SUITE + THE ORDERING PINS, plus the H0 pins for D-HP-1
(one numbering), D-HP-2 (the numbered receipt menu) and D-HP-4 (the trace instruments).

WHY THIS FILE EXISTS. The D-PQ HANDLE-2 defect is the canonical case: `[N3-N4]` and comma-joined shapes
were invisible to BOTH the render pass and `verify._HANDLE` -- a regex-shaped grammar with twelve
independent consumers and no table asserting they agree. D-HP widens that surface by design, so the table
is a PREREQUISITE, not a follow-up. This closes standing task #46 ("verify _HANDLE pins").

THE SUITE'S RULE, from the plan: one table of TOKEN SHAPES x TWELVE CONSUMERS, asserting agreement OR a
RECORDED, NAMED divergence -- and asserting the OUTCOME, not only the parse (per D-HP-3:
`register._level_tokens` returns `[]` AND `reg.sanitize` drops zero bytes for every shape).

SEAM-ANCHOR LAW: every anchor below was RE-RESOLVED against HEAD before it was written down. Four of the
plan's twelve had drifted and are corrected here: consumer 4 is answer.py:4242 (not :4072), consumer 7 is
eval.py:71 (not :66), consumer 9 is orchestrator.py:1713 (not :1710), consumer 12 is unchanged. The rest
verified correct on re-read.
"""
from __future__ import annotations

import re

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import citations as cit
from leviathan.graphrag import dossier as dos
from leviathan.graphrag import eval as ev
from leviathan.graphrag import orchestrator as orc
from leviathan.graphrag import register as reg
from leviathan.graphrag import tracekeys as tk
from leviathan.graphrag import verify as vf

# ── THE TOKEN SHAPES ──────────────────────────────────────────────────────────────────────────────────
# Every shape either reader can produce, plus the two that LOOK like handles and must never be read as
# ones. `_H_MEMBER_ANY` (verify.py:97) is why the bare-continuation forms are here at all: "continuation
# behind a PREFIXED lead: prefix optional" is LEGAL, and it is the exact leak D-HP-3 closes in register.py.
HANDLE_SHAPES = (
    "[N1]", "[E7]", "[N1b]", "[E1b]",
    "[N1, N2]", "[E1, E2]", "[N5, 10, 12]", "[N1, 23]", "[N13, 14]",
    "[N1-N6]", "[E1-E4]", "[N1" + chr(0x2013) + "N6]", "[N1 - N4]", "[N1;N2]", "[E1 and E2]",
)   # ^ ASCII SOURCE: the en-dash variant is built from its CODEPOINT, the discipline verify._QUOTE_EDGE
    #   states and the one answer.py:3753 restates -- a literal U+2013 in a fixture is invisible in a diff.
# THE BARE-LEAD SOLITARY FORM, held out of the shared table because it is a MEASURED, NAMED divergence and
# not an oversight. `verify._handle_members("[3]")` returns `[("E", 3)]` -- "a bare `[3]` returns
# [("E", 3)] -- the pre-CYCLE-9 reading, byte for byte" (verify.py:109-112) -- so the PRODUCER reads it as
# a handle. register.py deliberately does NOT: `_CIT_HANDLE` decides whether a sentence is CITED, and a
# bracketed bare integer is indistinguishable from a bracketed PRICE (`[1450]`). Admitting it there would
# exempt a fabricated level from the derivation gate, which is a fail-OPEN. Direction: TIGHTENING, same
# reasoning as the year-range fence below. Pinned in `test_divergence_bare_solitary_handle`.
BARE_SOLITARY = "[3]"
# NOT HANDLES, and the whole reason the lead's prefix is mandatory (verify.py:85-92): "`[1980-1990]` and
# `[5900-9999]` are not [handles], because their lead is bare and a bare lead still demands prefixed
# continuations". The second is a PRICE BAND -- reading it as a handle would stop it being an unbacked
# level, i.e. would make the price-target gate pass by being weakened.
NON_HANDLE_SHAPES = ("[1980-1990]", "[5900-9999]")


# ══ D-HP-3 -- THE ONE-PRODUCER CHANGE, ASSERTED AS AN OUTCOME ═════════════════════════════════════════

def test_dhp3_register_level_tokens_never_reads_a_handle_member_as_a_level():
    """THE MEASURED DEFECT, pinned so it cannot return: before D-HP-3,
    `register._level_tokens("Use of [N1, 23] fell.")` returned `['23']` and `[N13, 14]` returned `['14']`.
    `_NUM_NOISE` scrubbed only the SOLITARY `\\[[EN]\\d+\\]` shape while the bare-continuation member form
    is explicitly legal to `verify._HANDLE`, so a grouped handle's members became candidate PRICE LEVELS
    -- and handle-prose raises grouped-handle density BY DESIGN."""
    for shape in HANDLE_SHAPES:
        sent = f"Palm olein use of {shape} fell in the quarter."
        assert reg._level_tokens(sent) == [], f"{shape} shed a level token"


def test_dhp3_register_sanitize_drops_zero_bytes_for_every_handle_shape():
    """THE OUTCOME, NOT ONLY THE PARSE. Under the OUTLOOK register the derivation gate is fail-closed --
    "every sentence carrying an uncited level token is STRIPPED" -- so before the fix a sentence was
    deleted in full FOR CITING ITS EVIDENCE IN A GROUPED TOKEN.

    RECORDED DIVERGENCE FROM THE PLAN'S TEXT (D-HP-3 says the strip is "under FENCED"). MEASURED at H0:
    `_level_tokens` is consulted only on the OUTLOOK branch of `_is_banned_sentence`, so the STRIP fired
    on OUTLOOK, not FENCED. On FENCED the sentence survived but `unbacked_levels` /
    `unbacked_level_count` -- the `price_target_backed` teeth -- still charged the member digit on EVERY
    register. Both legs are pinned below; the fix is identical either way."""
    for shape in HANDLE_SHAPES:
        sent = f"Palm olein use of {shape} fell in the quarter."
        assert reg.sanitize(sent, market_register=reg.OUTLOOK) == sent, f"{shape} stripped on OUTLOOK"
        assert reg.sanitize(sent, market_register=reg.FENCED) == sent, f"{shape} stripped on FENCED"
        assert reg.unbacked_levels(sent) == [], f"{shape} charged as an unbacked level"
        assert reg.unbacked_level_count(sent) == 0


def test_dhp3_the_bare_lead_year_range_fence_survives_the_fix():
    """THE NAMED DIVERGENCE FROM `orchestrator._HANDLE_TOKEN_RX` (D-HP-6 consumer 8), asserted rather than
    described. The orchestrator's spelling makes the LEAD member's prefix OPTIONAL. Copying that VERBATIM
    into a LEVEL scrubber -- which is what D-HP-3's letter says -- re-opens the hazard verify._HANDLE
    closed deliberately. MEASURED: with the orchestrator spelling copied verbatim,
    `_level_tokens('band [5900-9999] held.')` goes `['5900','9999']` -> `[]`, and a bracketed price band
    stops being an unbacked level. register.py therefore requires the LEAD to carry its prefix --
    `verify._HANDLE`'s own rule, and the rule this wave's CHOSEN PRODUCER already enforces. Direction:
    TIGHTENING. Continuations stay prefix-optional, which is the whole leak."""
    for shape in NON_HANDLE_SHAPES:
        sent = f"The band {shape} held all quarter."
        assert reg._level_tokens(sent), f"{shape} was scrubbed -- the price-target gate just fail-opened"
        assert not reg._CIT_HANDLE.search(sent), f"{shape} read as a citation -- the derivation gate too"
        # ...and the divergence is REAL, not hypothetical: the orchestrator's RX does match it.
        assert orc._HANDLE_TOKEN_RX.fullmatch(shape)


def test_dhp3_register_cit_handle_sees_every_grouped_form():
    """The SECOND half of consumer 6. `_CIT_HANDLE` decides whether a sentence is CITED at all
    (`outlook_derivation_ok`, `_is_banned_sentence`, `unbacked_levels`). Solitary-only meant a sentence
    whose only citation was `[N1, N2]` read as UNCITED -- the same regression vector, opposite seam."""
    for shape in HANDLE_SHAPES:
        assert reg._CIT_HANDLE.search(f"stocks fell {shape} sharply"), f"{shape} read as uncited"


# ══ D-HP-6 -- THE TWELVE-CONSUMER TABLE ══════════════════════════════════════════════════════════════
# Each entry: (id, anchor, predicate, GROUPED-AWARE?). "Grouped-aware" is the agreement axis: a consumer
# that sees `[N1, N2]` and `[N1-N6]` as ONE token, or a NAMED divergence recorded in the test that reads
# it. The predicate is `bool(match)` on the shape ALONE (fullmatch semantics where the consumer scans a
# whole token, search semantics where it scans prose).

def _n_shapes():
    return [s for s in HANDLE_SHAPES if s.startswith("[N")]


def _e_shapes():
    return [s for s in HANDLE_SHAPES if s.startswith("[E")]


def test_divergence_bare_solitary_handle():
    """NAMED DIVERGENCE 1 of 4, and the reasoning is the same shape as the year-range fence: the PRODUCER
    reads `[3]` as an [E] handle; `register._CIT_HANDLE` refuses it because a bracketed bare integer is
    indistinguishable from a bracketed PRICE, and admitting it would exempt a fabricated level from the
    derivation gate. Direction: TIGHTENING (register can only ever charge MORE, never fewer, levels)."""
    assert vf._HANDLE.fullmatch(BARE_SOLITARY)
    assert vf._handle_members(BARE_SOLITARY) == [("E", 3)]
    assert not reg._CIT_HANDLE.fullmatch(BARE_SOLITARY)
    assert reg._level_tokens("the band [1450] held.") == ["1450"]      # ...and this is what it protects


def test_consumer_01_answer_n_handle_rx_is_grouped_and_ranged_aware():
    """answer.py:3759 `_N_HANDLE_RX` / :3763 `_N_RANGE_RX` -- the D-PQ HANDLE-2 fix, dash codepoint set
    at :3757. THE REFERENCE for the [N] side, on every GROUPED and RANGED form.

    NAMED DIVERGENCE 2 of 4, MEASURED HERE AND HANDED OFF, NOT FIXED: `_N_HANDLE_RX` carries no `[a-z]?`
    suffix, so `[N1b]` is INVISIBLE to it -- while `cit.unify` genuinely MINTS that id (a letter-suffixed
    id is a sibling ROW of a call already counted; `ids == ["N1", "N1b", "N1c", "N2"]` is pinned at
    test_cycle5_renderer_fixes.py:90) and `_E_HANDLE_RX` and `verify._HANDLE` both parse it.
    WHY IT IS NOT FIXED HERE: `_N_MEMBER_RX` is `N?(\\d+)`, so widening the token regex alone would resolve
    `[N1b]` onto call 1's HEADLINE row rather than the `b` SIBLING row -- converting inert debris into a
    MIS-BINDING, which is the wave's #1 risk. The correct fix is suffix-aware member resolution and it
    belongs with D-HP-11/D-HP-12. Pinned as-is so H1 cannot widen the regex without confronting this."""
    for s in _n_shapes():
        if s == "[N1b]":
            assert an._N_HANDLE_RX.fullmatch(s) is None       # <- the divergence, pinned
            assert an._E_HANDLE_RX.fullmatch("[E1b]") and vf._HANDLE.fullmatch(s)
            continue
        assert an._N_HANDLE_RX.fullmatch(s), f"consumer 1 blind to {s}"


def test_consumer_02_answer_e_handle_rx_is_grouped_and_ranged_aware():
    """answer.py:4518 `_E_HANDLE_RX` / :4520 `_E_RANGE_RX`."""
    for s in _e_shapes():
        assert an._E_HANDLE_RX.fullmatch(s), f"consumer 2 blind to {s}"


def test_consumer_03_scaffold_foreign_handle_rx_is_a_recorded_divergence():
    """answer.py:2718 `_SCAFFOLD_FOREIGN_HANDLE_RX` -- SOLITARY-ONLY. RECORDED DIVERGENCE, benign
    direction: it guards the episode scaffold against a FOREIGN handle appearing in a synthesised bullet,
    and the scaffold emits only solitary handles it minted itself. Pinned so a widening is a decision."""
    assert an._SCAFFOLD_FOREIGN_HANDLE_RX.fullmatch("[E7]")
    assert not an._SCAFFOLD_FOREIGN_HANDLE_RX.fullmatch("[N1, N2]")


def test_consumer_04_dedup_collapse_is_comma_only_recorded_divergence():
    """answer.py:4242 (plan anchor :4072, DRIFTED) -- the dedup collapse
    `re.sub(r"(\\[N\\d+(?:,\\s*N\\d+)*\\])(?:\\s*\\1)+", ...)`. COMMA-ONLY: a repeated RANGED token
    `[N1-N6] [N1-N6]` is not collapsed. RECORDED DIVERGENCE, cosmetic direction (a duplicate token
    survives; nothing is mis-bound). Asserted here so the widening lands as a decision, not a surprise."""
    src = _read("answer")
    assert r'(\[N\d+(?:,\s*N\d+)*\])(?:\s*\1)+' in src
    collapse = re.compile(r"(\[N\d+(?:,\s*N\d+)*\])(?:\s*\1)+")
    assert collapse.sub(r"\1", "[N1, N2] [N1, N2]") == "[N1, N2]"
    assert collapse.sub(r"\1", "[N1-N6] [N1-N6]") == "[N1-N6] [N1-N6]"      # the divergence


def test_consumer_05_verify_handle_is_the_producer_and_carries_the_year_fence():
    """verify.py:98 `_HANDLE` + :108 `_handle_members` -- the module that owns the CHOSEN digit-span
    producer (D-HP-3: `verify._claim_number_spans`, six exemptions, and the extractor dhp_census.json
    itself ran). It is grouped-aware AND it refuses the bare-lead year range."""
    for s in HANDLE_SHAPES:
        assert vf._HANDLE.fullmatch(s), f"consumer 5 blind to {s}"
    for s in NON_HANDLE_SHAPES:
        assert not vf._HANDLE.fullmatch(s), f"consumer 5 read {s} as a handle"
    assert vf._handle_members("[N1, 23]") == [("N", 1), ("N", 23)]           # the bare continuation
    assert vf._handle_members("[N1-N4]") == [("N", i) for i in (1, 2, 3, 4)]


def test_consumer_06_register_agrees_with_the_producer():
    """register.py:283 `_CIT_HANDLE` + :332 `_NUM_NOISE` -- NO LONGER A RECORDED DIVERGENCE (D-HP-3).
    Agreement is asserted against consumer 5 shape by shape, in BOTH directions."""
    for s in HANDLE_SHAPES:
        assert bool(reg._CIT_HANDLE.fullmatch(s)) == bool(vf._HANDLE.fullmatch(s)), s
    for s in NON_HANDLE_SHAPES:
        assert bool(reg._CIT_HANDLE.fullmatch(s)) == bool(vf._HANDLE.fullmatch(s)) is False, s


def test_consumer_07_eval_n_handle_rx_is_a_recorded_divergence():
    """eval.py:71 (plan anchor :66, DRIFTED) `_N_HANDLE_RX = re.compile(r"\\[N\\d+\\]")` -- SOLITARY-ONLY.
    RECORDED DIVERGENCE, and it UNDERCOUNTS cited [N] handles in the eval record, never overcounts."""
    assert ev._N_HANDLE_RX.fullmatch("[N1]")
    assert not ev._N_HANDLE_RX.fullmatch("[N1, N2]")


def test_consumer_08_orchestrator_is_the_reference_spelling_for_the_scrub():
    """orchestrator.py:252 `_HANDLE_TOKEN_RX` -- grouped-aware, and the reference D-HP-6 corrects 4/6/12
    against. It is DELIBERATELY looser than consumer 5 on the bare lead because it is a SCRUB for
    `_stated_values` (over-scrubbing a bracketed numeric range costs a magnitude, never a false caution);
    register.py could not inherit that looseness -- see the year-range fence test above.

    NAMED DIVERGENCE 3 of 4: the orchestrator's separator class is `[,;<dashes>]` only -- no `&`, no `/`,
    no `and`. `verify._H_SEP` (the producer) carries all three, and the corpus produced them ("Separators
    are the ones the corpus actually produced", answer.py:3754-3756). So `[E1 and E2]` sheds its member
    digits into `_stated_values`, which is the FALSE-CAUTION class CYCLE-6 BLOCKERS 1+2 closed for the
    comma form. NARROW, and the direction is a false CAUTION (never a false pass); handed off rather than
    fixed here because `_stated_values` is a live-serving caution path and R2 DEFERS its migration with
    the divergence RECORDED -- which is exactly what this line is."""
    for s in HANDLE_SHAPES:
        if s == "[E1 and E2]":
            assert orc._HANDLE_TOKEN_RX.fullmatch(s) is None  # <- the divergence, pinned
            assert vf._HANDLE.fullmatch(s) and reg._CIT_HANDLE.fullmatch(s)
            continue
        assert orc._HANDLE_TOKEN_RX.fullmatch(s), f"consumer 8 blind to {s}"


def test_consumer_09_emf_cited_n_is_a_recorded_divergence():
    """orchestrator.py:1713 (plan anchor :1710, DRIFTED) `re.findall(r"\\[N\\d+\\]", _ans)` -- the EMF
    `CitedN`, SOLITARY-ONLY. RECORDED DIVERGENCE: a dashboard counter, undercounting direction."""
    assert r'findall(r"\[N\d+\]", _ans)' in _read("orchestrator")
    assert re.findall(r"\[N\d+\]", "a [N1, N2] b [N3]") == ["[N3]"]


def test_consumer_10_cascade_search_is_a_recorded_divergence():
    """numbers/cascade.py:2939 `re.search(r"\\[N(\\d+)\\]", ln)` -- SOLITARY-ONLY, per-LINE, and it reads
    the FIRST handle on the line. RECORDED DIVERGENCE."""
    assert r'search(r"\[N(\d+)\]", ln)' in _read("cascade")
    assert re.search(r"\[N(\d+)\]", "row [N1, N2] here") is None


def test_consumer_11_dossier_handle_rx_is_gate_blocking_not_a_divergence():
    """dossier.py:95 `_HANDLE_RX` -- SOLITARY-ONLY, and GATE-BLOCKING for D-HP-16/D-HP-28 rather than a
    recorded divergence. `remap_body` (dossier.py:560-568) substitutes THROUGH it and drops a handle with
    no carried pair, but a GROUPED token DOES NOT MATCH IT AT ALL -- so it is neither remapped nor dropped
    and reaches the document as a stale LOCAL index inside the GLOBAL namespace. A silently wrong citation
    in a delivered document is the worst outcome in this wave.

    THIS TEST PINS THE DEFECT, NOT THE FIX: the fix belongs to D-HP-16/D-HP-28 (the dossier lane, H1+),
    and D-HP-28 may not open until it lands. Asserting the CURRENT blindness is what makes the gate
    condition machine-checkable instead of a sentence in a plan."""
    assert dos._HANDLE_RX.fullmatch("[E7]")
    assert dos._HANDLE_RX.fullmatch("[N1b]")
    assert dos._HANDLE_RX.fullmatch("[N1, N2]") is None       # <- the gate-blocking hole, pinned
    assert dos._HANDLE_RX.fullmatch("[N1-N6]") is None


def test_consumer_12_fe_cite_rx_is_a_recorded_divergence_and_keys_on_the_bare_digit():
    """apps/terminal/src/views/note/citations.ts:89 `CITE = /\\[([A-Za-z]?)(\\d+)\\]/g` -- SOLITARY-ONLY
    (a grouped `[N1, N2]` never becomes a chip) AND digit-keyed (:94-99 `const key = m[2]`), which is the
    namespace collision D-HP-2's typed resolved map exists for. Read as TEXT: this suite owns no FE code,
    and the FE edit is D-HP-2's one knowing waiver of B2's "the FE never changes"."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "apps" / "terminal" / "src" / "views" / "note" / "citations.ts"
    if not p.exists():                                        # the FE is not vendored in every checkout
        pytest.skip("terminal app not present")
    src = p.read_text(encoding="utf-8", errors="replace")
    assert r"/\[([A-Za-z]?)(\d+)\]/g" in src                  # solitary-only, pinned
    assert "const key = m[2]" in src                          # ...and keyed on the BARE DIGIT


def _read(mod: str) -> str:
    from pathlib import Path
    root = Path(an.__file__).resolve().parent
    return {"answer": root / "answer.py", "orchestrator": root / "orchestrator.py",
            "eval": root / "eval.py", "cascade": root / "numbers" / "cascade.py",
            "verify": root / "verify.py"}[mod].read_text(encoding="utf-8", errors="replace")


# ══ D-HP-1 -- ONE LIST, ONE NUMBERING, THREE CONSUMERS ═══════════════════════════════════════════════

class _Node:
    """The two attributes `_l2_blocks` / `_render_order` / the flat-list comprehension actually read."""

    def __init__(self, nid, contract, kind, evidence, depth=0, relevance=0.0):
        self.id, self.contract, self.kind, self.evidence = nid, contract, kind, evidence
        self.depth, self.relevance = depth, relevance
        self.active, self.episodes, self.via_edge, self.silver = True, [], None, None


def _ev(source, sk, date="2026-05-12", text="stocks fell", driver=None):
    row = {"source": source, "source_key": sk, "date": date, "text": text}
    if driver:
        row["driver"] = driver
    return row


def _wave_interleaved_nodes():
    """THE EXACT SHAPE THAT BREAKS A PER-CONTRACT COUNTER (the D-HP-1 pin's fixture): (a) two contracts
    INTERLEAVED by wave -- `sg.nodes` is BFS-wave ordered and therefore NOT contract-contiguous -- and
    (b) a DUPLICATE `source_key` across nodes."""
    dup = _ev("usda_wasde", "sk_wasde")
    return [
        _Node("palm_oil_bmd", "palm_oil_bmd", "contract", [_ev("mpob", "sk_mpob")]),
        _Node("soybean_oil_cbot", "soybean_oil_cbot", "contract", [_ev("usda_gain", "sk_gain")]),
        _Node("black_sea", "palm_oil_bmd", "driver", [dup, _ev("reuters", "sk_reuters")], depth=1),
        _Node("biofuel", "soybean_oil_cbot", "driver", [dict(dup)], depth=1),      # the duplicate
    ]


def _text_disagreeing_nodes():
    """THE FIXTURE WHERE RENDER ORDER AND `uniq` ORDER DISAGREE ON THE TEXT (H0 review, the blocker).

    ONE DOCUMENT (`sk_w`) hit under TWO contracts with DIFFERENT passages -- which is the ordinary case,
    not a corner: `source_key` is a DOCUMENT key and evidence.py:314 builds one record PER PROPOSITION
    under it. In FLAT (`_render_order`) order `uniq[1]` is the WHEAT-side passage; in RENDER order
    (`_l2_blocks` regroups by contract) the CORN-side passage is met first. The first H0 build rendered
    the corn passage under `[E2]` while `cit.unify`'s payload, the FE chip snippet and the verifier's
    quote pool all carried the wheat one. The previous fixture could not see this: its duplicate carried
    IDENTICAL text (`dup` / `dict(dup)`), so the text axis was invisible to every assertion."""
    return [
        _Node("corn_cbot", "corn_cbot", "contract", [_ev("mpob", "sk_mpob", text="mpob chunk")]),
        _Node("wheat_cbot", "wheat_cbot", "contract", [_ev("usda_wasde", "sk_w",
                                                          text="WHEAT-SIDE PASSAGE")]),
        _Node("black_sea", "corn_cbot", "driver", [_ev("usda_wasde", "sk_w", text="CORN-SIDE PASSAGE",
                                                       driver="black_sea")], depth=1),
    ]


def test_dhp1_menu_index_equals_unify_index_equals_the_verifier_index():
    """THE D-HP-1 PIN, as the plan words it: prompt index == unify index == the index verify resolves,
    on the exact shape that breaks a per-contract counter.

    Before the hoist these were THREE derivations -- the contract-regrouped render, the flat wave-ordered
    list, and `uniq` -- and they coincided only by luck."""
    nodes = _wave_interleaved_nodes()
    order = an._render_order(nodes, None)
    evidence = [{**h, "contract": n.contract} for n in order for h in n.evidence]
    uniq = an._uniq_evidence(evidence)
    ordinals = an._evidence_ordinals(uniq)

    # (1) the dedup actually bit: 5 raw rows, 4 unique source_keys.
    assert len(evidence) == 5 and len(uniq) == 4

    # (2) MENU == UNIFY. `cit.unify` stamps `E{i}` positionally off the SAME list.
    cits = [c for c in cit.unify(uniq, None) if c.kind == "evidence"]
    for c in cits:
        assert ordinals[c.payload["source_key"]] == int(c.id[1:]), f"{c.id} disagrees with the menu"

    # (3) MENU == VERIFIER. `[E{i}]` means `uniq[i-1]` -- the list `verify_citations` now receives.
    for sk, i in ordinals.items():
        assert uniq[i - 1]["source_key"] == sk

    # (4) ...and the render is NOT contract-contiguous, which is the whole point of the fixture.
    assert [n.contract for n in order] != sorted(n.contract for n in order)


def test_dhp1_the_text_rendered_under_e_i_is_uniq_i_minus_1s_text():
    """THE FOURTH AXIS OF THE SAME INVARIANT, AND THE ONE THE FIRST BUILD BROKE (H0 review, the blocker).

    Index agreement is NOT the invariant. D-HP-1 (iii) says "`[E{i}]` means `uniq[i-1]` IN ALL THREE
    PLACES" -- so the TEXT the model reads under `[E{i}]` must be `uniq[i-1]`'s text, because that is the
    text `cit.unify` puts in the payload, the text the FE chip shows, and the text
    `verify._check_evidence_handle` runs its quote / lexical-overlap check against. Rendering the
    locally-encountered chunk instead manufactures a NEW false-caution class (quote_mismatch /
    no_lexical_overlap) on a sentence that correctly quoted what it was SHOWN -- inside G1 clause
    (3)/(4)'s declared set, on the D-HP arm, invisible to the index pins.

    THE MENU IS THE LEDGER OR THE GRAMMAR DIES AT BIRTH."""
    nodes = _text_disagreeing_nodes()
    order = an._render_order(nodes, None)
    evidence = [{**h, "contract": n.contract} for n in order for h in n.evidence]
    uniq = an._uniq_evidence(evidence)
    menu = an._evidence_menu(uniq)

    # THE FIXTURE REPRODUCES: flat order says WHEAT, render order meets CORN first.
    assert uniq[1]["source_key"] == "sk_w" and uniq[1]["text"] == "WHEAT-SIDE PASSAGE"
    _render_first = next(h for cid in dict.fromkeys(n.contract for n in order)
                         for n in order if n.contract == cid
                         for h in n.evidence if h["source_key"] == "sk_w")
    assert _render_first["text"] == "CORN-SIDE PASSAGE", "the fixture stopped reproducing the disagreement"

    # THE RENDER, replicating `_l2_blocks`' regrouping exactly (one `rendered` set across blocks).
    seen: set[str] = set()
    lines = [ln for cid in dict.fromkeys(n.contract for n in order)
             for n in order if n.contract == cid
             for ln in an._ev_block(n.evidence, menu, seen).splitlines()]

    # (4) for EVERY ordinal, the line carrying `[E{i}]` carries `uniq[i-1]`'s text.
    for sk, (i, rep) in menu.items():
        labelled = [ln for ln in lines if ln.startswith(f"- [E{i}]")]
        assert len(labelled) == 1, f"[E{i}] labels {len(labelled)} rows -- the ledger property is gone"
        assert rep["text"] in labelled[0], f"[E{i}] does not carry uniq[{i - 1}]'s text"
        assert uniq[i - 1]["source_key"] == sk

    # ...and the passage the model was never given the address of is not sitting under someone's label.
    assert not any("CORN-SIDE PASSAGE" in ln and ln.startswith("- [E") for ln in lines)


def test_dhp1_the_menu_binding_is_one_object_not_two():
    """WHY `_evidence_menu` EXISTS AS A PAIR. A caller must not be able to hold the numbering without the
    row it binds -- that is the shape of the defect above. `_ev_block` reads the ROW out of the menu, so
    the derivation is `uniq[i-1]` by construction; and the menu is DERIVED from `_evidence_ordinals`, so
    there is still exactly ONE numbering derivation in answer.py (D-HP-1's whole point)."""
    uniq = [{"source": "s", "source_key": "a", "date": "2026-01-01", "text": "A"},
            {"source": "s", "source_key": "b", "date": "2026-01-01", "text": "B"}]
    assert an._evidence_menu(uniq) == {"a": (1, uniq[0]), "b": (2, uniq[1])}
    src = _read("answer")
    assert "return {sk: (n, uniq[n - 1]) for sk, n in _evidence_ordinals(uniq).items()}" in src


def test_dhp1_a_render_order_counter_would_have_disagreed():
    """THE NEGATIVE CONTROL for the pin above -- without it, test 1 could pass on a counter too. This
    reproduces the WITHDRAWN design (a counter threaded through the per-contract render loop) and asserts
    it disagrees with `unify` on this fixture. If this ever stops failing, the fixture stopped
    reproducing the defect and the pin above stopped measuring anything."""
    nodes = _wave_interleaved_nodes()
    order = an._render_order(nodes, None)
    counter, by_key = 0, {}
    for cid in dict.fromkeys(n.contract for n in order):          # the render's own regrouping
        for n in [x for x in order if x.contract == cid]:
            for h in n.evidence:
                counter += 1
                by_key.setdefault(h["source_key"], counter)
    evidence = [{**h, "contract": n.contract} for n in order for h in n.evidence]
    ordinals = an._evidence_ordinals(an._uniq_evidence(evidence))
    assert by_key != ordinals, "the per-contract counter agreed -- the fixture no longer reproduces"


def test_dhp1_uniq_evidence_skips_rows_with_no_source_key():
    """An item with no `source_key` has no durable identity to cite. That was ALREADY true of the footer
    and of `unify`; D-HP-1 only makes the MENU agree with them -- and `_ev_block` renders such a row in
    its pre-D-HP shape, offering NO handle for a receipt the reader could never be shown."""
    rows = [_ev("mpob", "sk_a"), {"source": "x", "date": "2026-01-01", "text": "t"}]
    assert an._uniq_evidence(rows) == [rows[0]]
    out = an._ev_block(rows, an._evidence_menu(an._uniq_evidence(rows)), set())
    assert out.splitlines()[0].startswith("- [E1][T")
    assert not out.splitlines()[1].startswith("- [E")


# ══ D-HP-2 -- THE RECEIPT MENU ═══════════════════════════════════════════════════════════════════════

def test_dhp2_row_shape_keeps_the_trust_tag_and_leads_with_the_ordinal():
    """SHAPE, CORRECTED TO PRESERVE THE TRUST TAG (review P13). The draft's `- [E7] (USDA WASDE, ...)`
    silently deleted `[T1]-[T4]`, which is the row's LEADING token today and which the persona depends on
    TWICE, verbatim (answer.py:117-120 and :260-263). The shipped shape is `- [E7][T2] (...)`, matching
    the [N] rows' idiom at numbers/cascade.py:1747 and dossier.py's `notes_block`."""
    rows = [_ev("usda_wasde", "sk_w", driver="black_sea_corridor")]
    out = an._ev_block(rows, an._evidence_menu(rows), set())
    assert out.startswith("- [E1][T")
    out = an._ev_block(rows, {"sk_w": (7, rows[0])}, set())
    assert out.startswith("- [E7][T")
    assert "{driver: black_sea_corridor}" in out
    assert re.match(r"- \[E7\]\[T\d\] \(usda_wasde, reported 2026-05-12\)", out)


def test_dhp2_ev_block_is_byte_identical_when_the_menu_is_omitted():
    """OMIT-WHEN-DEFAULT, the estate's idiom: with `menu=None` the block is the pre-D-HP bytes, so the
    flag-off / verify-off branch, every other caller AND the dossier sub-answer lane (D-HP-16) are
    unchanged by construction, not by promise."""
    rows = [_ev("usda_wasde", "sk_w"), _ev("mpob", "sk_m")]
    assert an._ev_block(rows) == an._ev_block(rows, None, None)
    assert "[E" not in an._ev_block(rows)


def test_dhp2_a_duplicate_source_key_renders_once_and_is_cross_referenced():
    """D-HP-1: "A duplicate `source_key` renders once at its first block and is cross-referenced by its
    GLOBAL ordinal elsewhere. Blocks keep their headers; ordinals are global." The per-driver BLOCK
    STRUCTURE is preserved because the D-MW-30 admission-provenance header has nowhere else to live and
    D-HP-25 lever (ii) rides it.

    THE CROSS-REFERENCE NAMES THE FIRST LABEL THE TEXT RENDERED UNDER, AND NEVER ITSELF (H0 review). The
    first build emitted `- [E3]... (same item as [E3] above)` -- a tautology in a prompt whose entire job
    is to teach that an ordinal is an ADDRESS, and (with the blocker above) a row that pointed at a label
    carrying text it did not carry. The cross-reference row now carries NO `[E]` label of its own, which
    is what makes `[E3]` unambiguously the first one AND keeps the ledger property the menu is named for:
    each `[E{i}]` labels exactly ONE row, and that row has the text. THE EXACT STRING IS PINNED."""
    dup = _ev("usda_wasde", "sk_w", text="the full passage", driver="black_sea")
    menu, seen = {"sk_w": (3, dup)}, set()
    first = an._ev_block([dup], menu, seen)
    second = an._ev_block([dict(dup)], menu, seen)
    assert first == ("- [E3][T1] (usda_wasde, reported 2026-05-12) {driver: black_sea} "
                     "the full passage")
    assert second == ("- [T1] (usda_wasde, reported 2026-05-12) {driver: black_sea} "
                      "(same item as [E3] above)")
    assert "the full passage" not in second
    assert not second.startswith("- [E")                  # it names the FIRST label, never itself
    assert second.count("[E3]") == 1


def test_dhp2_ledger_line_gives_e_a_range_symmetric_with_n():
    """THE LEDGER LINE (answer.py's GROUNDING LEDGER): the [E] clause becomes a RANGE, symmetric with [N].
    The shipped asymmetry was visible in one sentence -- [N] got a range, [E] got a count -- and a count
    is not addressable. Read off the SOURCE because the line is built inline in `_answer_l2`.

    THE RANGE RIDES THE MENU (D-HP-16, H0 review): "each mapping to the item tagged with it above" is a
    claim ABOUT RENDERED ROWS, so the ONE surviving occurrence of the pre-D-HP asymmetric sentence is the
    menu-off (dossier) reversion branch, where nothing tagged anything. It must never appear on the
    menu-on path, and n_ev must be EXACT there."""
    src = _read("answer")
    assert '[E] handles run [E1]..[E{n_ev}]' in src
    assert 'n_ev = len(_uniq)' in src                                   # ...and n_ev is now EXACT
    # the pre-D-HP asymmetric form survives EXACTLY ONCE, in the menu-off reversion branch
    assert src.count('Cite AT MOST {n_ev} distinct [E] handles') == 1
    _menu_off = src.index('_e_clause = f"Cite AT MOST {n_ev} distinct [E] handles')
    assert src.rindex("n_ev = sum(len(getattr(n, \"evidence\", []) or []) for n in sg.nodes)") < _menu_off
    assert src.index("if _menu_on:") < _menu_off


def test_dhp2_cache_law_the_menu_stays_in_the_volatile_half():
    """CACHE LAW, CORRECTED (review G29): the evidence rows were ALREADY volatile -- `_l2_blocks` returns
    `(stable, volatile)` and every evidence block is appended to `vlines`, while the stable half is hop
    annotations + `_context_block` only. NUMBERING THEM CHANGES NO CACHED BYTE AND THE MENU STAYS WHERE IT
    IS. (Moving the menu's POSITION is D-HP-25 lever (iii) and belongs to the reserve arm -- doing it here
    would confound the one untried reserve lever with a named mechanism.)"""
    src = _read("answer")
    assert 'vlines.append(f"--- DATED EVIDENCE for {cid} ---\\n"' in src
    assert 'stable.append("\\n".join(lines))' in src
    # the numbering is threaded into the VOLATILE emit sites only
    assert src.count("_ev_block(n.evidence, menu, _seen_rows)") == 2


def test_dhp2_typed_resolved_map_is_additive_and_namespace_explicit():
    """THE TYPED RESOLVED MAP. `verify_citations` keys `resolved` on the BARE DIGIT and the LIVE FE chip
    path keys the lookup the same way, so with a DENSE [E] menu over 24-63 rows and [N] running N1..N24,
    E7/N7 co-exist on nearly every turn and a reader can be shown the WRONG RECEIPT for a CORRECTLY BOUND
    handle.

    RECORDED DIVERGENCE FROM D-HP-2's LETTER ("ALONGSIDE the legacy digit keys", i.e. in the SAME dict):
    it ships as a SIBLING. MEASURED REASON -- `eval._hits` iterates `resolved.items()` to compute
    `n_cited`/`n_cited_upstream`, the RESERVE's standing bar (R6, HELD), so duplicate typed keys would
    DOUBLE a live gate instrument in H0, silently."""
    verifier = {"resolved": {"7": {"source": "usda_wasde"}, "12": {"source": "mpob"}}}
    typed = an._typed_resolved(verifier)
    assert typed == {"E7": {"source": "usda_wasde"}, "E12": {"source": "mpob"}}
    assert verifier["resolved"] == {"7": {"source": "usda_wasde"}, "12": {"source": "mpob"}}   # untouched
    assert an._typed_resolved({}) == {} and an._typed_resolved(None) == {}


def test_dhp2_the_trust_re_home_is_coupled_to_dhp9_and_the_coupling_is_pinned():
    """THE DEFERRAL, MADE MACHINE-CHECKABLE (H0 review, minor #6 -- and the plan clause is amended, not
    silently resequenced: see the H0 FOLD note at D-HP-2).

    D-HP-2 says the persona's trust instruction is re-homed IN THE SAME CHANGE as the [E] row shape. H0
    shipped the row shape and deferred the persona edit, because the clause's OWN reason for the re-home
    is that D-HP-9 deletes `sources` -- the ordering surface the instruction acts through -- and the
    replacement (the renderer ordering `## Sources` by tier) is D-HP-9 too. Re-homing at H0 would open a
    window where `sources` still ships and NOTHING orders it.

    SO THE COUPLING IS PINNED FROM THE OTHER SIDE: the ordering sentence must be PRESENT today. The day
    D-HP-9 deletes `sources`, this reds, and the persona has to move in that same change."""
    src = _read("answer")
    order_clause = "in `sources` ORDER citations most-trusted (lowest T) FIRST"
    assert src.count(order_clause) == 2, "the persona's two trust seams (answer.py:119, :262)"
    # ...and the [T] tag the instruction depends on is still the row's LEADING token after the ordinal.
    rows = [_ev("usda_wasde", "sk_w")]
    assert an._ev_block(rows, an._evidence_menu(rows), set()).startswith("- [E1][T")


# ══ D-HP-16 -- THE DOSSIER SUB-ANSWER LANE DOES NOT GET THE MENU AT H0 ═══════════════════════════════

def _l2_fixture(monkeypatch):
    """A REAL `Subgraph` of REAL `GroundedNode`s with a duplicate `source_key` across two contracts --
    driven through the SHIPPED `_l2_blocks`, not a re-implementation of it."""
    from leviathan.graphrag import planner as pl
    monkeypatch.setattr(an, "_context_block", lambda g, c: f"CTX {c}")
    nodes = [pl.GroundedNode(kind="contract", id="corn_cbot", contract="corn_cbot", depth=0,
                             relevance=1.0, evidence=[_ev("mpob", "sk_mpob", text="mpob chunk")]),
             pl.GroundedNode(kind="driver", id="black_sea", contract="corn_cbot", depth=1,
                             relevance=0.9, evidence=[_ev("usda_wasde", "sk_w", text="CORN-SIDE")])]
    return pl.Subgraph(seeds=["corn_cbot"], nodes=nodes)


def test_dhp16_the_dossier_sub_answer_lane_renders_pre_dhp_bytes(monkeypatch):
    """D-HP-16 (H0 review, the major). The dossier's 5-12 sub-answers are ORDINARY quick/deep turns
    through `orchestrator.respond` (dossier.py:4, :932), so H0's numbered menu reaches the ONE lane whose
    output-side handle plumbing is not fixed until D-HP-28 -- after G1+G2. `dossier._HANDLE_RX` (:95)
    does not match a grouped token at all (pinned as the defect in consumer 11), so `remap_body` neither
    remaps nor drops it and a stale LOCAL index reaches a DELIVERED document inside the GLOBAL namespace:
    the plan's own "worst outcome in this wave". An addressable dense menu is the strongest available
    nudge toward multi-citation grouping, so raising the INPUT density before the OUTPUT fix lands is the
    exact ordering D-HP-28 forbids.

    THE LEVER IS THE ONE THE PLAN ALREADY GATES THIS LANE AT: `run_subquery` (where the plan pins the
    control preset, and where `allow_shape_escalation=False` already rides). Thread-scoped, per sub-call,
    both configs -- never a process env, which a concurrent desk turn would inherit."""
    sg = _l2_fixture(monkeypatch)
    seen: list = []

    def _fake_respond(question, **kw):
        seen.append({"menu_on": an._handle_menu_on(),
                     "blocks": an._l2_blocks(sg, None, asof=None)[1],
                     "mode": kw.get("mode")})
        return {"answer": "ok"}

    for cfg in ("deep", "quick"):
        dos.run_subquery({"question": "q", "config": cfg}, asof=None, graph=None, respond=_fake_respond)

    # (1) the override is ON (i.e. the menu is OFF) inside BOTH configs' sub-calls ...
    assert [r["menu_on"] for r in seen] == [False, False]
    assert [r["mode"] for r in seen] == ["deep", "quick"]
    # (2) ... and it does NOT leak: the desk lane outside the sub-call still renders the menu.
    assert an._handle_menu_on() is True
    # (3) THE BYTES. What the sub-answer is shown is the pre-D-HP render, exactly.
    pre_dhp = an._l2_blocks(sg, None, asof=None)[1]
    with an.handle_menu_override(False):
        assert an._l2_blocks(sg, None, asof=None, menu=None)[1] == pre_dhp
    assert not any("[E" in b for b in pre_dhp)
    # (4) and the gate is the ONE the body actually reads, on BOTH bodies (the onehop rollback lane too).
    src = _read("answer")
    assert "_menu_on = _handle_menu_on()" in src
    assert "_ev_menu = _evidence_menu(_uniq) if _menu_on else None" in src
    assert "_ev_menu = _evidence_menu(uniq) if _handle_menu_on() else None" in src


def test_dhp16_the_menu_override_is_thread_scoped_and_exception_safe():
    """The `composition_census_override` idiom, verbatim: token-reset in a `finally`, so an exception
    inside the block can never leave a thread pinned to the dossier's setting."""
    assert an._handle_menu_on() is True
    with pytest.raises(RuntimeError):
        with an.handle_menu_override(False):
            assert an._handle_menu_on() is False
            raise RuntimeError("boom")
    assert an._handle_menu_on() is True
    with an.handle_menu_override(None):                    # None = no override = the default (ON)
        assert an._handle_menu_on() is True


# ══ D-HP-4 -- THE TRACE INSTRUMENTS ══════════════════════════════════════════════════════════════════

def test_dhp4_keys_are_appended_at_the_tail_never_inserted():
    """THE 12f COLUMN-SHIFT LESSON: eval.py SPLATS this registry IN ORDER, so inserting a key shifts every
    later column in every per-answer record and a stored artifact stops being comparable across waves.
    "Append, never sort" is not a style note."""
    keys = tk.TRACE_RECORD_KEYS
    assert keys[-5:] == ("prose_handles", "error", "floor_cause", "bare_digit_count", "citation_resolved")
    for older in ("number_handles", "rerank_lane", "walk_shape", "escalation_decision"):
        assert keys.index(older) < keys.index("prose_handles")
    assert len(set(keys)) == len(keys)


def test_dhp4_turn_error_is_not_expressible_and_the_literal_keys_are_used():
    """D-HP-4(b), REWRITTEN IN FULL. `TRACE_RECORD_KEYS` lifts keys VERBATIM BY THEIR OWN NAME and
    eval.py's `**{k: trace.get(k) ...}` has NO rename hook (the renamed form exists only for the OTHER
    tuple, `DECISION_RECORD_KEYS`, declared as (decision_key, record_column) pairs). A `turn_error` entry
    would lift a key NOTHING STAMPS -- an all-None column forever, i.e. a PERFECT reproduction of the
    C2/U3 silent-lift class this registry exists to kill, in the very item that cites it."""
    assert "turn_error" not in tk.TRACE_RECORD_KEYS
    assert "error" in tk.TRACE_RECORD_KEYS and "floor_cause" in tk.TRACE_RECORD_KEYS
    src = _read("eval")
    assert "for k in tk.TRACE_RECORD_KEYS}" in src            # verbatim lift, no rename hook
    assert 'trace": {"error": "watchdog_timeout"' in src      # ...and `error` IS stamped
    assert '"floor_cause"' in _read("orchestrator")           # ...and so is `floor_cause`


def test_dhp4_the_tripwire_is_positive_not_the_attribution_keys():
    """AC3 correction 4a, MEASURED, and the reason this pin is written as a POSITIVE test. The four dead
    max-arm rows carry `error` None, `floor_cause` ABSENT, `answer` None and `mode_decision` POPULATED --
    neither eval's except-branch nor the orchestrator floor produced them. `error`/`floor_cause`
    ATTRIBUTE a failure once something detects it; the only fields that provably separate a LIVE turn from
    all three failure shapes are `walk_shape is not None` AND `synth_usage is not None`. G1 clause (5) and
    G3 rung 4 read all four, which is why all four must be registered."""
    for k in ("walk_shape", "synth_usage", "error", "floor_cause"):
        assert k in tk.TRACE_RECORD_KEYS


def test_dhp4_the_three_failure_shapes_are_no_longer_byte_indistinguishable():
    """D-HP-4(b)'s PIN, as the plan words it: "a crashed row lands with `error` non-None and
    `claim_count == 0`, and a floored row with `floor_cause` non-None, so the three can never again be
    byte-indistinguishable".

    THAT IS PRECISELY THE DEFECT AC3 EXPOSED: three separate failure seams -- eval's outer except, the
    watchdog, and the orchestrator's deterministic floor -- reached the artifact looking the same, and the
    plan named the wrong one because the artifact could not tell them apart. The columns exist now; each
    row below is the LITERAL out-dict each seam builds."""
    # the LITERAL out-dict eval.py's outer except builds (eval.py:1769-1771)
    crashed = {"q": {"id": "x"}, "out": {"answer": "(answer failed: boom)", "contract": None,
                                         "structured": None, "evidence": [], "intent": None,
                                         "number_calls": [], "citations": [], "model": None,
                                         "trace": {"error": "RuntimeError: boom"}}}
    # ...and the LITERAL out-dict `_timeout_row` builds (eval.py:1224-1225). Constructed rather than
    # called because `_timeout_row` runs `score(q, out)`, which needs a whole deck row -- an instrument
    # pin must not drag the deck contract in. The source line is asserted verbatim below.
    watchdog = {"q": {"id": "y"},
                "out": {"answer": "(turn watchdog timeout at 4200s)", "contract": None,
                        "structured": None, "evidence": [], "intent": None, "number_calls": [],
                        "citations": [], "model": None,
                        "trace": {"error": "watchdog_timeout",
                                  "degraded_model": "(watchdog_timeout)"}}}
    assert '"trace": {"error": "watchdog_timeout", "degraded_model": "(watchdog_timeout)"}' in _read("eval")
    floored = {"q": {"id": "z"}, "out": {"answer": "...", "structured": {},
                                         "trace": {"floor": "evidence_only", "floor_cause": "no_evidence"}}}

    def lift(row):
        tr = (row["out"].get("trace") or {})
        return {k: tr.get(k) for k in tk.TRACE_RECORD_KEYS}

    assert lift(crashed)["error"] == "RuntimeError: boom" and lift(crashed)["floor_cause"] is None
    assert lift(watchdog)["error"] == "watchdog_timeout"
    assert watchdog["out"]["trace"]["degraded_model"] == "(watchdog_timeout)"   # the AV2 discriminator
    assert lift(floored)["error"] is None and lift(floored)["floor_cause"] == "no_evidence"
    # ...and a crashed row makes no claims, so `claim_count == 0` is the conjunct G1 clause (5) reads.
    # (Read through the SAME projection `_per_answer_record` uses -- the row has no rubric, and building
    # one would drag `score()`'s deck contract into an instrument pin.)
    for row in (crashed, watchdog):
        v = ((row["out"].get("trace") or {}).get("citation_verifier")) or {}
        assert v.get("claim_count", 0) == 0 and not v.get("enabled")
    # THE FOURTH SHAPE (AC3 correction 4a, MEASURED) carries NONE of these -- which is why the TRIPWIRE is
    # positive and lives on walk_shape/synth_usage, not on error/floor_cause.
    dead = {"q": {"id": "w"}, "out": {"answer": None, "structured": None,
                                      "trace": {"rerank_lane": {"requests": 3}}}}
    assert lift(dead)["error"] is None and lift(dead)["floor_cause"] is None
    assert lift(dead)["walk_shape"] is None and lift(dead)["synth_usage"] is None


def test_dhp4_bare_digit_count_uses_the_chosen_producer_and_gates_nothing():
    """D-HP-4(c). ONE PRODUCER (D-HP-3): `verify._mask_handles` + `_claim_numbers_with_decimals`, which
    delegates to `verify._claim_number_spans` -- the extractor dhp_census.json itself ran, so every count
    is denominated in the same producer every census percentage is. ALWAYS ON, both polarities.

    It replaces `number_unbacked` as the fabrication tripwire: 248 of the 478 killed-class events are
    `number_unbacked` and D-HP-12 routes exactly those sentences into `bare_digit`, so a successor family
    reading only the strip classes would score a RENAME as a win. This counter cannot be renamed into --
    it counts what the model TYPED, before any renderer, verifier or strip."""
    st = {"tldr": "Palm oil rose 12.5% to 4,250 MYR [E1].", "mechanism": "Stocks fell to 1.62 MMT in 2024."}
    assert an._count_bare_digits(st) == 3                     # 12.5 / 4,250 / 1.62 -- 2024 is a year
    assert an._count_bare_digits({"tldr": "Stocks fell [E1].", "mechanism": ""}) == 0
    assert an._count_bare_digits({}) == 0
    # handle DIGITS are masked, never counted -- the whole point of `_mask_handles`
    assert an._count_bare_digits({"tldr": "cited [N13, 14] and [E7]", "mechanism": ""}) == 0
    src = _read("answer")
    assert src.count('"bare_digit_count": _bare_digits') == 2  # BOTH bodies, unconditional


def test_dhp4_citation_resolved_is_stamped_on_both_bodies():
    """D-HP-4(d), the COMPUTABILITY PREREQUISITE for G1 clause (6). WITHOUT IT NO [E] BINDING IS AUDITABLE
    FROM ANY STORED ARTIFACT: the record carries `served_rows` (so an [N] handle -> row join exists) but
    neither `resolved` nor the evidence list, so the spot-audit is not computable for [E] handles at
    all."""
    src = _read("answer")
    assert src.count('"citation_resolved": _typed_resolved(verifier)') == 2


def test_dhp4_the_arm_stamp_rides_the_baseline_header(monkeypatch):
    """THE ARM STAMP (review P17; the section-2 law). Today a treatment artifact and a control artifact
    differ ONLY by `git_commit`, so D-HP-19's BRIDGE RUN has no join key. It lands in the SAME change as
    the trace keys and BEFORE any arm runs -- an arm identity added after the arms have run is not an
    identity. R9: the knob is a RESOLVED PRESET value, not a process env, because the escalation seam
    swaps the knob dict WHOLE (orchestrator.py:2138-2139).

    THE ENV IS DELETED BEFORE THE ASSERTION (H0 review): the first build's pin read `is None` with the
    ambient environment, so it was ENVIRONMENT-DEPENDENT -- `GRAPHRAG_HANDLE_PROSE=on` reded the suite
    (measured: 1 failed, 37 passed) while the defect it was meant to catch was that the same value
    STAMPED the arm "on"."""
    monkeypatch.delenv("GRAPHRAG_HANDLE_PROSE", raising=False)
    src = _read("eval")
    assert '"handle_prose": _handle_prose_arm(mode),' in src
    assert ev._handle_prose_arm("deep") is None               # H0: no preset declares the knob yet
    assert ev._handle_prose_arm("no_such_mode") is None        # never raises on an unknown name


def test_dhp4_the_kill_switch_is_one_way(monkeypatch):
    """R9: `GRAPHRAG_HANDLE_PROSE` is demoted to a ONE-WAY KILL SWITCH -- it can turn the treatment OFF
    and is recorded when it does, but IT CANNOT TURN IT ON (that is what the dark presets are for).

    BOTH DIRECTIONS ARE PINNED (H0 review). The first build returned `kill or None` on the no-preset
    branch, so a stray `GRAPHRAG_HANDLE_PROSE=on` stamped the arm "on" when nothing had turned the
    treatment on -- and this is the JOIN KEY D-HP-19's bridge run rides. An artifact that names an arm
    that did not run is strictly worse than one that names none."""
    for off in ("off", "0", "false", "kill", "OFF", " off "):
        monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", off)
        assert ev._handle_prose_arm("deep") == "off", off
    for on in ("on", "1", "true", "deep_hp", "yes"):
        monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", on)
        assert ev._handle_prose_arm("deep") is None, f"the env stamped an arm nothing turned on: {on}"


# ══ D-HP-6 -- THE ORDERING PINS ══════════════════════════════════════════════════════════════════════

def test_ordering_pin_a_render_passes_run_inside_the_verifier_gate_and_before_the_snapshot():
    """(a) Every D-HP render pass runs INSIDE `if verifier.get("enabled"):` and BEFORE the
    `body_pre_sanitize` snapshot, so THE JUDGE CAN NEVER GRADE UNRENDERED HANDLE PROSE (the PROVENANCE
    dict is pairwise_judge.py:124-135 and marks `body_pre_sanitize` EXACT).

    THE PIN IS NOT SUFFICIENT AND THE PLAN SAYS SO (review C19): rung 5 `raw_fields`
    (pairwise_judge.py:179-180) re-renders the PRE-VERIFY draft, which under handle-prose is unrendered
    handle prose, and it is reachable whenever `GRAPHRAG_STRIP_AUDIT` is on. The per-row `provenance`
    whitelist is the actual fence; this pin only keeps rungs 3-4 honest."""
    src = _read("answer")
    gate = src.index('if verifier.get("enabled"):')
    resolve = src.index("_resolve_number_handles(structured, extra_number_calls)", gate)
    snap = src.index("sanitize_input_snapshot(body_pre_sanitize=_pre_sanitize)", gate)
    assert gate < resolve < snap


def test_ordering_pin_b_the_five_pass_repair_stack_keeps_its_order():
    """(b) `_resolve_number_handles` -> `_dedup_number_handles` -> `_prune_orphan_evidence_handles` ->
    `_tidy_handle_debris` -> `_tidy_strip_orphans`. The [E] resolver (D-HP-10, H1) inserts BEFORE the
    prune, never after: debris closes frames the prunes empty, and orphans close the paragraph seam a
    sentence-drop opened. The ORDER was correct against HEAD; only the plan's anchor had drifted."""
    src = _read("answer")
    start = src.index('if verifier.get("enabled"):')
    order = ["_resolve_number_handles(", "_dedup_number_handles(", "_prune_orphan_evidence_handles(",
             "_tidy_handle_debris(", "_tidy_strip_orphans("]
    at = [src.index(name, start) for name in order]
    assert at == sorted(at), f"the five-pass repair stack drifted: {order} at {at}"


def test_ordering_pin_d_verify_off_emits_no_handle_contract():
    """(d) (review G9; the section-2 mutual-exclusion law) with `GRAPHRAG_VERIFY=off` the system prompt is
    BYTE-IDENTICAL to the flag-off prompt on BOTH bodies. The renderer cannot run on that branch, so the
    contract must not be emitted on it.

    AT H0 THIS HOLDS TRIVIALLY -- `_system` carries no handle-prose contract yet (D-HP-7/D-HP-8 mint it at
    H1) -- and the pin is written NOW so H1 cannot land the contract without tripping it."""
    base = an._system()
    for token in ("handle-prose", "HANDLE PROSE", "never type a number"):
        assert token not in base
    assert an._system() == base                               # ...and it is deterministic


def test_ordering_pin_c_is_a_recorded_handoff_not_a_pin_yet():
    """(c) (review G16/C9/P14) the PLANNING REGION property is popped from `structured` BEFORE
    `verify_citations` and therefore before `body_pre_sanitize`; `claim_count` must be byte-identical with
    and without one. THE PROPERTY DOES NOT EXIST AT H0 -- it is D-HP-7's `plan`, minted at H1 -- so there
    is nothing to pin and pinning a name that nothing stamps is the C2/U3 class D-HP-4(b) refuses.
    RECORDED: this pin lands WITH D-HP-7, in the same change, and G1 does not run without it."""
    assert '"plan"' not in an._answer_tool()["input_schema"]["properties"]
