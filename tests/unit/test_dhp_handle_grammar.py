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
    """answer.py `_N_HANDLE_RX` / `_N_RANGE_RX` -- the D-PQ HANDLE-2 fix. THE REFERENCE for the [N] side,
    on every GROUPED and RANGED form.

    H0's NAMED DIVERGENCE 2 of 4 IS CLOSED BY D-HP-11/12 (H1), WHICH IS WHERE H0 HANDED IT. The H0 pin
    read `_N_HANDLE_RX.fullmatch("[N1b]") is None` and said, verbatim, "pinned as-is so H1 cannot widen
    the regex without confronting this". H1 confronted it: the regex is widened AND the member resolution
    is suffix-aware IN THE SAME CHANGE, which is the two-sided condition H0 attached to the widening.

    H1 FIX Z8 RE-PIN -- THE WIDENING IS THE TREATMENT'S GRAMMAR, NOT THE ESTATE'S. The first build shipped
    it ungated on BOTH arms, which moved the CONTROL arm's rendered prose (a suffixed token in a value slot
    deletes a whole control-arm sentence) and its `number_handles` census. `_N_HANDLE_RX` is therefore the
    pre-H1 bytes and `_N_HANDLE_HP_RX` is the suffix-aware twin, selected per turn by `_n_token_rx`. The
    agreement H0 asked for holds where it matters -- on the arm that runs the contract."""
    for s in _n_shapes():
        assert an._N_HANDLE_HP_RX.fullmatch(s), f"consumer 1 (treatment) blind to {s}"
        if "b" not in s:                                   # the suffixed shape is the treatment's alone
            assert an._N_HANDLE_RX.fullmatch(s), f"consumer 1 blind to {s}"
    # the readers of a suffixed token agree ON THE TREATMENT ARM, which is where the contract binds
    assert an._N_HANDLE_HP_RX.fullmatch("[N1b]") and an._E_HANDLE_RX.fullmatch("[E1b]")
    assert vf._HANDLE.fullmatch("[N1b]")
    # ...and the CONTROL arm keeps its pre-H1 blindness, which is what makes it a control (FIX Z8)
    assert an._N_HANDLE_RX.fullmatch("[N1b]") is None
    assert an._n_token_rx(True) is an._N_HANDLE_HP_RX and an._n_token_rx(False) is an._N_HANDLE_RX
    # ...and the SUFFIX TRAVELS: widening alone would have resolved `[N1b]` onto call 1's HEADLINE row,
    # which is a MIS-BINDING (a real, cited, WRONG number) and the wave's #1 risk.
    assert an._n_handle_pairs("[N1b]") == [(1, "b")]
    assert an._n_handle_pairs("[N1, N1b]") == [(1, ""), (1, "b")]      # two ROWS of one call, not one
    assert an._n_handle_members("[N1, N1b]") == [1]                    # ...and the index view is unmoved


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
    """apps/terminal/src/views/note/citations.ts -- the FE cite grammar. RE-PINNED BY T1-7
    (CASCADE_HOME_AND_SMALL_ITEMS), which is the same change that moved it, per the estate's re-pin-in-the-
    same-commit law. Two things moved and one thing did not:

      * MOVED: the grammar gained an optional ROW SUFFIX (`[N1b]`, a completion row of call N1 minted by
        `citations._mint_row_citations`), and it is now declared ONCE as an exported SOURCE STRING
        (`CITE_SRC`) because two renderers tokenize handles -- this module and `inlineFormat.parseInline`
        -- and the two hand-copied regexes drifting apart is how the suffix bug lived.
      * MOVED: `const key = m[2]` became `citeResolve`, which tries the sibling's own entry (`'1b'`) FIRST
        and only then the call's headline entry under the bare digit.
      * DID NOT MOVE, AND IS THE DIVERGENCE THIS TEST EXISTS FOR: it is still SOLITARY-ONLY (a grouped
        `[N1, N2]` never becomes a chip) and the FALLBACK is still the BARE DIGIT, which is the namespace
        collision D-HP-2's typed resolved map exists for.

    Read as TEXT: this suite owns no FE code, and the FE edit is D-HP-2's one knowing waiver of B2's "the
    FE never changes". The grammar is then re-derived from the file and exercised, so the divergence is
    pinned by BEHAVIOR and not only by a string that the next edit can drift past silently."""
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "apps" / "terminal" / "src" / "views" / "note" / "citations.ts"
    if not p.exists():                                        # the FE is not vendored in every checkout
        pytest.skip("terminal app not present")
    src = p.read_text(encoding="utf-8", errors="replace")
    assert r"export const CITE_SRC = '\\[([A-Za-z]?)(\\d+)([a-z]?)\\]'" in src   # ONE grammar, exported
    assert "const CITE = new RegExp(CITE_SRC, 'g')" in src    # ...global scan, no anchor -> solitary-only
    assert "resolved[digits + suffix] : undefined) ?? resolved[digits]" in src   # BARE DIGIT is the fallback
    # The same source string, run as a Python regex (a JS single-quoted `\\[` is one backslash + `[`).
    js = re.search(r"export const CITE_SRC = '([^']+)';", src).group(1)
    rx = re.compile(js.replace("\\\\", "\\"))
    assert rx.fullmatch("[E7]") and rx.fullmatch("[1]") and rx.fullmatch("[N1b]")   # the T1-7 widening
    assert rx.search("a [N1, N2] b") is None                  # <- solitary-only, still pinned


def _read(mod: str) -> str:
    from pathlib import Path
    root = Path(an.__file__).resolve().parent
    return {"answer": root / "answer.py", "orchestrator": root / "orchestrator.py",
            "eval": root / "eval.py", "cascade": root / "numbers" / "cascade.py",
            "verify": root / "verify.py",
            "dossier": root / "dossier.py"}[mod].read_text(encoding="utf-8", errors="replace")


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


def test_dhp2_the_labelled_rows_header_comes_from_the_row_the_label_binds():
    """H1 RESIDUAL 10.9(1). The H0 blocker fix bound the TEXT under `[E{i}]` to `uniq[i-1]`; the HEAD
    (source / reported date / event date) and the `{driver: ...}` tag were still read off the LOCALLY
    ENCOUNTERED row. That is the same defect one field over, and it is reachable on the L2 body by
    construction: `_l2_blocks` regroups by CONTRACT while `uniq` is flat `_render_order` order, and
    `source_key` is a DOCUMENT key (evidence.py builds one record per PROPOSITION under it), so the row a
    block meets first and the row `uniq` names can genuinely differ in event date and driver.
    A receipt whose date labels another chunk's passage is a WRONG receipt even when the passage is right.

    THE FIXTURE MAKES THE TWO ROWS DIFFER ON EVERY FIELD THE HEAD READS -- text, event date and driver --
    because a fixture whose rows agree cannot see this axis at all (the H0 review's own lesson)."""
    local = _ev("usda_wasde", "sk_w", text="the LOCAL chunk", driver="black_sea")
    local["event_date"] = "2026-04-01"
    rep = _ev("usda_wasde", "sk_w", text="THE BOUND passage", driver="la_nina")
    rep["event_date"] = "2026-01-15"
    out = an._ev_block([local], {"sk_w": (4, rep)}, set())
    assert out == ("- [E4][T1] (usda_wasde, reported 2026-05-12; event 2026-01-15) "
                   "{driver: la_nina} THE BOUND passage")
    assert "2026-04-01" not in out and "black_sea" not in out    # the local head never labels bound text
    # ...and the CROSS-REFERENCE row keeps its LOCAL head deliberately: it binds no text, and its head +
    # driver tag + admission provenance are what place THIS occurrence in THIS per-driver block.
    seen = {"sk_w"}
    xref = an._ev_block([local], {"sk_w": (4, rep)}, seen)
    assert xref == ("- [T1] (usda_wasde, reported 2026-05-12; event 2026-04-01) "
                    "{driver: black_sea} (same item as [E4] above)")


def test_dhp2_a_menu_requires_its_rendered_set_and_a_bare_set_is_legitimate():
    """H1 RESIDUAL 10.9(3), NARROWED BY FIX Z3. `_ev_block(evidence, menu, rendered)` with `menu` but no
    `rendered` compiles, reads plausibly, and SILENTLY BREAKS THE LEDGER PROPERTY: with no caller-owned set
    to carry the cross-reference state across blocks, a `source_key` met twice renders its text TWICE under
    the SAME `[E{i}]`, so an ordinal stops naming exactly one row. That half still refuses.

    THE OTHER HALF MUST NOT REFUSE, AND THE SYMMETRIC GUARD WAS A LATENT CRASH ON THE ROLLBACK LANE. The
    ONE-HOP body passes `rendered=set()` UNCONDITIONALLY while its menu is None whenever
    `_handle_menu_on()` is False -- i.e. on every `dossier.run_subquery` sub-call -- with no try/except
    around the prompt-assembly loop, so `GRAPHRAG_PLANNER=onehop` (the DOCUMENTED incident rollback) raised
    ValueError out of `answer()` for every dossier sub-answer. A set that accrues nothing renders nothing
    wrong; symmetry was never the invariant."""
    rows = [_ev("usda_wasde", "sk_w")]
    menu = an._evidence_menu(rows)
    with pytest.raises(ValueError):
        an._ev_block(rows, menu, None)                       # numbering with no ledger state
    # the menu-off shape the one-hop body actually emits: pre-D-HP bytes, no raise
    assert an._ev_block(rows, None, set()) == an._ev_block(rows)
    an._ev_block(rows, menu, set())                          # ...and the D-HP path still works
    an._ev_block(rows)


def test_dhp2_the_one_hop_menu_off_assembly_renders(monkeypatch):
    """FIX Z3, AT THE CALL SITE THE SUITE NEVER EXERCISED. The pin above asserted the raise and no test
    ever ran the one-hop body's own `_ev_block(hits, _ev_menu, _seen_rows)` with the menu off, so the
    conformance suite was green on a crash that every dossier sub-answer would have taken. This reproduces
    the exact three arguments that body builds under `handle_menu_override(False)`."""
    hits = [_ev("usda_wasde", "sk_w"), _ev("mpob", "sk_m")]
    with an.handle_menu_override(False):
        assert an._handle_menu_on() is False
        _ev_menu = an._evidence_menu(hits) if an._handle_menu_on() else None
        _seen_rows: set = set()                              # answer.py's own unconditional local
        block = an._ev_block(hits, _ev_menu, _seen_rows)
    assert "[E" not in block and "usda_wasde" in block


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
    claim ABOUT RENDERED ROWS, so the pre-D-HP asymmetric sentence survives only on the menu-off (dossier)
    reversion branch, where nothing tagged anything. It must never appear on the menu-on path.

    **[H1 -- READ OFF THE PRODUCER, NOT THE BODY.]** D-HP-16 required the one-hop body to gain a ledger
    line of its own under handle-prose (it had none, which under handle-ONLY prose is a numbered menu with
    no statement of which addresses exist -- D2 restored on the rollback lane). Two bodies emitting one
    sentence means ONE derivation or none, so the sentence is now `_grounding_ledger` and this pin asserts
    the OUTCOME on both branches instead of the inline text."""
    src = _read("answer")
    assert an._grounding_ledger(7, 3, menu_on=True).endswith(
        "[E] handles run [E1]..[E7], each mapping to the item tagged with it above; "
        "[N] handles run [N1]..[N3].")
    assert an._grounding_ledger(0, 0, menu_on=True).endswith(
        "Emit NO [E] handles (there are no evidence items); emit NO [N] handles (there are no number "
        "rows).")
    # the pre-D-HP asymmetric form survives on the MENU-OFF branch only, and nowhere else in the file
    assert "Cite AT MOST" in an._grounding_ledger(7, 3, menu_on=False)
    assert "handles run [E1]" not in an._grounding_ledger(7, 3, menu_on=False)
    assert src.count("Cite AT MOST") == 1                              # one spelling, in the producer
    # ONE PRODUCER, BOTH BODIES: L2 unconditionally, one-hop under handle-prose (D-HP-16)
    assert src.count("_grounding_ledger(") == 3                         # def + two call sites
    # PA-8(b): the L2 site now also passes SERVED ROWS (`n_rows`) -- `n_num` still governs the [N] range,
    # which is what this pin is about, so the call-site assertion follows the signature.
    assert "_ledger_line = _grounding_ledger(n_ev, n_num, menu_on=_menu_on, n_rows=n_srv)" in src
    assert "volatile_blocks.append(_grounding_ledger(" in src


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
    D-HP-9 deletes `sources`, this reds, and the persona has to move in that same change.

    **[H1 -- THE COUPLING HAS FIRED, AND IT IS DISCHARGED.]** D-HP-9 now deletes `sources` CONDITIONALLY
    (`_answer_tool(handles=True)`), so the ordering surface is gone on the treatment lane and still there
    on every other turn. The re-home therefore had to be conditional too, and it is: the sentence stays
    in `_SYSTEM_MENTOR` verbatim for the control lane, and `_SYSTEM_HANDLES` SUPERSEDES IT BY NAME on the
    treatment lane, re-homing the ordering onto the menu's per-row [T] tag (which D-HP-2 already ships in
    the row head, and which this pin's second half asserts is still the leading token). Both halves are
    asserted below so neither can move without the other."""
    src = _read("answer")
    order_clause = "in `sources` ORDER citations most-trusted (lowest T) FIRST"
    assert src.count(order_clause) == 2, "the persona's two trust seams (answer.py:119, :262)"
    assert order_clause in an._system()                         # the CONTROL lane keeps it, verbatim
    assert "ORDER citations most-trusted first" in an._SYSTEM_HANDLES     # ...and the treatment re-homes
    assert "[T1]-[T4] trust tag" in an._SYSTEM_HANDLES
    assert "FLAG the disagreement exactly as before" in an._SYSTEM_HANDLES
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
    # H1 RE-PIN (D-HP-14): `wrong_slot_audit` appends AFTER the five H0 keys, so the H0 slice moves left by
    # one and NOTHING before it moves at all. Same law, same reason -- this pin is re-anchored to the H0
    # block's own position rather than re-listing it against the tail, so a later append re-pins one line.
    assert keys[-12:-7] == ("prose_handles", "error", "floor_cause", "bare_digit_count",
                            "citation_resolved")
    assert keys[-7] == "wrong_slot_audit"
    # H1 RE-PIN (FIX W2 / finding NF-2): `slot_orphan_dropped` appends AFTER it. Same law, same one-line
    # re-anchor -- the H0 slice moves left by one more and nothing before it moves at all.
    assert keys[-6] == "slot_orphan_dropped"
    # H1b RE-PIN (D-HP-15): `episode_spans_validated` appends after THAT. Third application of the same
    # law in this wave, and the third one-line re-anchor -- which is the whole point of writing the pin
    # against the tail rather than against a frozen absolute index.
    assert keys[-5] == "episode_spans_validated"
    # G1 AMENDMENT A3 RE-PIN (2026-08-14): `plan_tokens` -- the popped planning region's SIZE, never its
    # text -- appends after THAT. Fourth application of the same law, fourth one-line re-anchor, and
    # nothing before the H0 slice moves at all.
    assert keys[-4] == "plan_tokens"
    # G1 REMEDIATION D2(b) RE-PIN (2026-08-14): `evidence_slot_dropped` -- clause (2b)'s remedy census --
    # appends after THAT. Fifth application of the same law, fifth one-line re-anchor.
    assert keys[-3] == "evidence_slot_dropped"
    # D-HP-25 RE-PIN (2026-08-15, plan 10.30.6): `evidence_geo_dropped` -- V2's [E] geo-containment
    # census -- appends after THAT. SIXTH application of the same law and the sixth one-line re-anchor,
    # which is exactly what a tail-anchored pin is for. NOTE WHAT DID *NOT* NEED A LINE: V1's own two
    # counters (`geo_checked` / `geo_mismatch`) ride INSIDE `number_handles` and mint no top-level key,
    # so they shift no column at all -- the `escalation_decision` idiom, one registered key per producer.
    assert keys[-2] == "evidence_geo_dropped"
    # D-LD SITTING-A RE-PIN (2026-08-18): `tables_queried` -- the per-table usage census, the estate's
    # first -- appends after THAT. SEVENTH application of the same law and the seventh one-line re-anchor.
    assert keys[-1] == "tables_queried"
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
    assert ev._handle_prose_arm("deep") is None               # the CONTROL preset never declares the knob
    assert ev._handle_prose_arm("no_such_mode") is None        # never raises on an unknown name
    # H1 (D-HP-8): the presets exist now, so the column is no longer all-None -- it NAMES THE ARM, which is
    # the whole reason it landed before the arms did. ONE PRODUCER: the stamp is the leaf's own resolution
    # (`reasoning_modes.handle_prose_arm`), the same function the serving seam's boolean is built from, so
    # an artifact cannot disagree with the turn it describes.
    assert "_rm.handle_prose_arm(_rm.knobs(mode), kill," in src
    monkeypatch.delenv("GRAPHRAG_VERIFY", raising=False)
    monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
    for hp in ("quick_hp", "deep_hp", "esc_hp", "esc_r_hp"):
        assert ev._handle_prose_arm(hp) == "on", hp


def test_dhp4_the_arm_stamp_reads_the_full_verdict_including_both_rollback_lanes(monkeypatch):
    """H1 FIX Z9. Serving resolves the bundle with `answer._handle_prose_active`, which is FALSE under
    either documented rollback lane -- `GRAPHRAG_VERIFY=off` (section 2's mutual-exclusion law: every
    handle pass runs inside `if verifier.get("enabled")`) and `GRAPHRAG_MENTOR_VOICE=off` (`_system`
    returns the LEGACY persona, which carries neither the menu's vocabulary nor the four superseded
    spans). The artifact stamp read only the preset knob and the kill switch, so on either lane it named
    "on" a run the treatment PROVABLY did not run -- the H0 arm-stamp defect, reopened by the second lane,
    on the join key D-HP-19's bridge run rides.

    ONE PRODUCER, BOTH SEAMS: the lanes live in the leaf and both callers thread their env values in, so
    the serving boolean and the artifact stamp are the same expression evaluated on the same inputs."""
    from leviathan.graphrag import reasoning_modes as rm
    monkeypatch.delenv("GRAPHRAG_HANDLE_PROSE", raising=False)
    kn = rm.knobs("deep_hp")
    for lane in ("GRAPHRAG_VERIFY", "GRAPHRAG_MENTOR_VOICE"):
        monkeypatch.delenv("GRAPHRAG_VERIFY", raising=False)
        monkeypatch.delenv("GRAPHRAG_MENTOR_VOICE", raising=False)
        assert an._handle_prose_active(kn) is True and ev._handle_prose_arm("deep_hp") == "on"
        monkeypatch.setenv(lane, "off")
        assert an._handle_prose_active(kn) is False, lane      # the turn did not run the treatment
        assert ev._handle_prose_arm("deep_hp") == "off", lane  # ...and the artifact no longer says it did
        # a CONTROL row on the same lane still names no arm: nothing was selected there to report off
        assert ev._handle_prose_arm("deep") is None, lane
    # ...and "is the treatment SELECTED" is deliberately still lane-blind (the two questions differ)
    monkeypatch.setenv("GRAPHRAG_VERIFY", "off")
    assert an._handle_prose_on(kn) is True


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
        # H1: it cannot turn a PRESET off either by being truthy -- a non-kill value is simply not a lever.
        assert ev._handle_prose_arm("deep_hp") == "on", on
    # ...and the kill BEATS the preset, which is the whole point of keeping it: an incident needs a lever
    # that does not require a taskdef registration, and a one-way switch cannot drift a gate arm.
    monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", "off")
    assert ev._handle_prose_arm("deep_hp") == "off"


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
    # the ANCHOR is the call, not its argument list: D-HP-11/12 add keywords to this pass and the pin is
    # about POSITION (inside the verifier gate, before the snapshot), which no signature change may move.
    resolve = src.index("_resolve_number_handles(structured, extra_number_calls", gate)
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
    # H1 LANDED THE TWO PASSES THIS PIN WAS WRITTEN AGAINST, so the stack is SEVEN and the two new
    # positions are pinned here, where the ordering law lives -- not left to the item's own test file.
    seven = ["_drop_bare_digit_sentences(", "_resolve_number_handles(", "_dedup_number_handles(",
             "_resolve_evidence_handles(", "_prune_orphan_evidence_handles(",
             "_tidy_handle_debris(", "_tidy_strip_orphans("]
    at7 = [src.index(name, start) for name in seven]
    assert at7 == sorted(at7), f"the seven-pass stack drifted: {seven} at {at7}"
    # ...and the two positions are load-bearing for a MEASURED reason each, so they are asserted as
    # reasons and not merely as an order:
    #   D-HP-12's remedy is FIRST -- `_resolve_number_handles` writes ROW values into the prose, so a
    #   digit-lint behind it reads the ENGINE's digits as the MODEL's and deletes the sentences the
    #   renderer just filled in (reproduced in test_dhp_renderer's negative control).
    assert at7[0] < at7[1]
    #   D-HP-10's [E] resolver is BEFORE the prune -- this one asks "does the index name a row at all",
    #   the prune asks "did the reader actually GET the row", keyed on the footer's emission decision.
    assert at7[3] < at7[4]


# ── D-HP-15 / plan 10.10(b) + 10.13: THE FOUR EPISODE-SEAM ORDERING PINS (P1-P4) ──────────────────────
# 10.10(b) OWED TWO OF THESE AS PINS RATHER THAN OBSERVATIONS, and the note is explicit about why: both
# properties were true at HEAD, both are what discharge the D-HP-15 sequencing hazard, and both were
# "properties of the current call sequence, not guarantees". A later reorder must red CI instead of
# re-opening a hazard a fold note only recorded as absent. P3 and P4 are H1b's own.
def _body_src(body: str) -> str:
    import inspect
    return inspect.getsource(getattr(an, body))


@pytest.mark.parametrize("body", ["_answer_l2", "answer"])
def test_ordering_pin_p1_sources_are_synthesized_before_the_episode_scaffold(body):
    """P1 (plan 10.10(b), first property). `_synthesize_sources` runs BEFORE `_maybe_scaffold_episodes`
    in BOTH bodies.

    THE HAZARD IT DISCHARGES, named by D-HP-15's own sequencing clause: the scaffold writes
    `structured['sources']` directly, so under D-HP-9's ledger deletion a scaffold running FIRST would
    leave `_document_source_rows` rendering the scaffold's synthesised rows AND NOTHING ELSE. The
    positional rows must already be present when the scaffold appends to them.
    AND THE DIRECTION IS PART OF IT (R1, already executed): `_synthesize_sources` mints `sources` FROM
    `verifier['resolved']`, never the reverse -- writing a ledger BEFORE verify would make
    `fabricated_citation` read 0 TAUTOLOGICALLY, which is G1 clause (1)'s whole subject."""
    src = _body_src(body)
    assert src.index("_synthesize_sources(structured, verifier)") < src.index("_maybe_scaffold_episodes(")
    # ...and the direction, asserted at the producer rather than re-derived here.
    doc = an._synthesize_sources.__doc__ or ""
    assert "resolved" in doc


@pytest.mark.parametrize("body", ["_answer_l2", "answer"])
def test_ordering_pin_p2_the_digit_lint_runs_before_the_episode_scaffold(body):
    """P2 (plan 10.10(b), second property). `_drop_bare_digit_sentences` runs BEFORE
    `_maybe_scaffold_episodes` in BOTH bodies.

    THE HAZARD: the scaffold RENDERS digits (a receipt date, a span's two years). A digit-lint behind it
    would read the ENGINE's own rendered digits as the MODEL's and delete the sentences the scaffold had
    just written -- the same class the seven-pass stack's own first position exists to prevent, one seam
    further down. `_validate_episode_spans` used to inherit the property for free by sitting beside the
    scaffold; since fold-2 it sits AHEAD of the lint instead, and P3 pins the stronger property."""
    src = _body_src(body)
    assert src.index("_drop_bare_digit_sentences(") < src.index("_maybe_scaffold_episodes(")


@pytest.mark.parametrize("body", ["_answer_l2", "answer"])
def test_ordering_pin_p3_the_span_fence_runs_ahead_of_every_pass_that_rewrites_its_text(body):
    """P3 (H1b's own, REWRITTEN AT FOLD-2 -- these five positions were one round old, not frozen law).
    `_validate_episode_spans` runs AFTER `verify_citations` and BEFORE the whole seven-pass stack, the
    scaffold and the humanizer, in BOTH bodies, SPELLED IDENTICALLY (D-HP-16's three-lane law).

    WHY IT MOVED, which is this pin's whole subject: A FENCE MUST NEVER WALK TEXT A PRIOR PASS REWROTE.
    Fold-1 placed it after the stack, and `_drop_bare_digit_sentences` -- treatment-only -- eats an
    ordered item's '1. ' marker as a bare-digit sentence. The fence then saw NO ITEMS in a numbered
    '## Episodes' section (driven end to end by the fold-1 verifier: items found on the treatment arm
    = [], on the control arm = [3, 4]), the fabricated window shipped uncharged, and an honest ordered
    item following a convicted one was read as a CONTINUATION and deleted without a charge. Walking
    marker-intact text closes both at the root: an ordered item is an item.

    EACH POSITION IS LOAD-BEARING, so each is asserted as a reason and not merely as an order:
      * AFTER `verify_citations` -- `claim_count` and checked/stripped are already final, so the STRIP
        RATE keeps its denominators when this pass folds its own class into the ledger.
      * BEFORE `_drop_bare_digit_sentences` -- the de-markering above. THIS IS THE FOLD-2 ROOT PIN.
      * BEFORE THE SEVEN-PASS STACK ENTIRELY (its last member is TIDY-2), so the fence is still OUTSIDE
        the stack's membership -- on the other side of it. That law is unchanged and it is about
        PRODUCERS: `_synth_ref_floor` mints episode refs ABOVE `len(uniq)` and `_resolve_evidence_
        handles` kills exactly those, so a PRODUCER relocated INTO the stack is destroyed by the
        treatment's own renderer. This pass mints nothing -- it only deletes convicted model prose --
        so running ahead of the stack costs it nothing and hands the stack an already-fenced page.
      * BEFORE `_maybe_scaffold_episodes` -- CONVICTIONS FIRST, SHAPE CAPS SECOND, so
        `_cap_absence_bullets`' majority rule counts the bullets that actually survive. UNCHANGED, and
        THE SCAFFOLD DID NOT MOVE WITH THE PASS: it stays at D-DT-1's four-constraint seam (P4).
      * BEFORE `_humanize_structured` -- one register pass over the surviving section, as for every
        other seam producer.
    AND THE ONE THING THE MOVE COST, ASSERTED SO IT CANNOT BE DISCOVERED LATER: this pass's deletions
    now fall in the A4b `postverify_* -> verified_*` interval (the handle passes') instead of
    `verified_* -> body_pre_sanitize` (the render seam's). There is NO position that is both above the
    digit lint and below the `verified_*` capture -- the capture closes the stack the lint opens -- and
    the deletions stay fully attributable through the declared class, the ONE ledger, and a trace key
    carrying its own denominator. Recorded at plan 10.15 with this reasoning."""
    src = _body_src(body)
    val = src.index("_validate_episode_spans(structured,")
    assert src.index("vf.verify_citations(") < val, "the strip-rate denominators would move"
    assert val < src.index("_drop_bare_digit_sentences("), "the fence would walk de-markered text"
    assert val < src.index("_tidy_strip_orphans("), "the fence would sit behind the seven-pass stack"
    assert val < src.index("_maybe_scaffold_episodes("), "the caps would count bullets already convicted"
    assert val < src.index("_humanize_structured(structured"), "the survivors would miss the register pass"
    # ...and the recorded consequence, asserted from BOTH ends so the interval named at plan 10.15 is
    # load-bearing rather than incidental: the deletions fall in `postverify_* -> verified_*`, i.e. the
    # A4b postverify capture is AHEAD of the pass and the `verified_*` capture is BEHIND it.
    assert src.index("postverify_mechanism=structured") < val, "the deletions escaped the A4b interval"
    assert val < src.index("verified_mechanism=structured"), "the interval move is not the recorded one"
    # ONE strip ledger, ONE WRITER: the charge rides `_fold_ledger_class` in both bodies, beside the pass.
    assert "_fold_ledger_class(verifier, _EPISODE_SPAN_UNBACKED_CLASS" in src


def test_ordering_pin_p4_the_four_constraint_seam_still_holds_after_the_insert():
    """P4 (H1b's own). Inserting P3's pass at the seam must NOT displace the scaffold from the ONE point
    satisfying D-DT-1's four constraints. Restated HERE, in the file that owns the ordering law, so the
    property is not readable only from the item's own suite (`test_ddt_scaffold_fork_basis` section F,
    which stays green and stays the primary pin)."""
    for body in ("_answer_l2", "answer"):
        src = _body_src(body)
        call = src.index("_maybe_scaffold_episodes(")
        assert src.index("vf.verify_citations(") < call
        assert src.index("verified_mechanism=structured") < call
        assert call < src.index("_humanize_structured(structured")
        assert call < src.index("render(structured")


def test_ordering_pin_d_verify_off_emits_no_handle_contract(monkeypatch):
    """(d) (review G9; the section-2 mutual-exclusion law) with `GRAPHRAG_VERIFY=off` the system prompt is
    BYTE-IDENTICAL to the flag-off prompt on BOTH bodies. The renderer cannot run on that branch, so the
    contract must not be emitted on it.

    NOW A REAL PIN (H1): `_system(handles=...)` exists, so the pin reads the seam that resolves it. Under
    `GRAPHRAG_VERIFY=off` the whole citation-truth chain is rolled back -- no splice, no prune, and
    `render()` falls back to the model's own `**Sources**` ledger -- so a prompt that still said "write
    the handle, we substitute the value" would put NUMBER-FREE, HANDLE-LITTERED prose on the reader's page.
    That is a rollback becoming a live defect, which is the whole of the folded G9 finding.
    `GRAPHRAG_MENTOR_VOICE=off` is the SECOND such lane and is pinned in the same breath: it returns
    `_SYSTEM_LEGACY`, a persona carrying neither the menu's vocabulary nor the four spans this contract
    supersedes."""
    hp = {"handle_prose": True}
    assert an._handle_prose_active(hp) is True                 # ...the treatment IS selected
    for env, val in (("GRAPHRAG_VERIFY", "off"), ("GRAPHRAG_MENTOR_VOICE", "off"),
                     ("GRAPHRAG_HANDLE_PROSE", "off")):
        monkeypatch.setenv(env, val)
        assert an._handle_prose_active(hp) is False, env       # ...and cannot run on this lane
        monkeypatch.delenv(env)
    base = an._system()
    assert an._system(handles=False) == base                   # OFF is byte-identical, not merely similar
    for token in ("HANDLE-PROSE", "you do not type figures"):
        assert token not in base and token in an._system(handles=True)


def test_ordering_pin_d2_the_verify_off_spelling_agrees_with_the_verifier_itself(monkeypatch):
    """THE SPELLING IS THE PIN, not the intent. `_handle_prose_active` re-spells verify.py's
    `os.environ.get("GRAPHRAG_VERIFY", "on") == "off"` locally (answer cannot import verify at module
    scope), and two spellings of one kill switch is exactly how a mutual-exclusion law rots: a future
    verify-side widening (`=0`, `=false`) would leave the persona emitting a contract on a lane whose
    renderer is dark. Asserted as an OUTCOME against the verifier's own `enabled` flag, both polarities."""
    hp = {"handle_prose": True}
    for val, expect_enabled in (("off", False), ("on", True), ("", True)):
        monkeypatch.setenv("GRAPHRAG_VERIFY", val)
        enabled = bool(vf.verify_citations({"tldr": "x", "mechanism": ""}, []).get("enabled"))
        assert enabled is expect_enabled
        assert an._handle_prose_active(hp) is enabled, val


def test_ordering_pin_c_the_planning_region_is_popped_before_the_verifier():
    """(c) (review G16/C9/P14), THE PIN THE PLAN SAYS G1 MAY NOT RUN WITHOUT -- and it is now real, in the
    same change as D-HP-7's `plan` property, exactly as H0 recorded the handoff.

    THE PROPERTY IS POPPED BEFORE `verify_citations`, ON BOTH BODIES, and the consequence is measured
    rather than argued: `claim_count` is the strip-rate denominator EVERY D-HP-17 successor metric divides
    by (`_SENT_SPLIT` over `tldr + " " + mechanism`, verify.py), the digit-lint charges inside the same
    function, and `render_answer_for_judge`'s rungs read `structured`. A plan left on the dict would
    inflate the denominator, fine the model for thinking in numbers, and stream its scratchpad.

    RE-ANCHORED (G1 AMENDMENT A3, 2026-08-14): the call is now `_plan_tokens(_pop_plan(structured))` on
    both bodies -- the region's TEXT is still returned and dropped on the floor at this exact position,
    and only its SIZE is kept. The POSITION is the contract this pin polices, and the position did not
    move; the wrapper is asserted too, so a future edit cannot quietly keep the text instead."""
    src = _read("answer")
    _POP = "\n    _plan_tok = _plan_tokens(_pop_plan(structured))"
    assert src.count(_POP) == 2                                # BOTH bodies, never one (`def` excluded)
    assert src.count("\n    _pop_plan(structured)") == 0       # ...and the bare form is gone from both
    for start in (0, src.index(_POP) + 1):
        pop = src.index(_POP, start)
        assert pop < src.index("vf.verify_citations(", pop)
    # ...and the OUTCOME: a plan on the dict cannot move the denominator, because it is not on the dict.
    with_plan = {"tldr": "Stocks fell [E1].", "mechanism": "## Mechanism\nThe balance tightened [E2].",
                 "plan": "cite E1 then E2. 12.5 vs 14.9. do not type these."}
    without = {k: v for k, v in with_plan.items() if k != "plan"}
    an._pop_plan(with_plan)
    assert "plan" not in with_plan and with_plan == without
    assert (vf.verify_citations(dict(with_plan), []).get("claim_count")
            == vf.verify_citations(dict(without), []).get("claim_count"))


# ══ D-HP-7 / D-HP-9 -- THE GRAMMAR: THE TOOL SCHEMA ══════════════════════════════════════════════════

_SHIPPED_OFF_SCHEMA = {
    "name": "emit_answer", "description": "Emit the reader-first structured answer.",
    "input_schema": {"type": "object", "properties": {
        "tldr": {"type": "string"}, "mechanism": {"type": "string"},
        "diagram_mermaid": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "object", "properties": {
            "ref": {"type": "integer"}, "source": {"type": "string"},
            "date": {"type": "string"}, "note": {"type": "string"}}}}},
        "required": ["tldr", "mechanism", "sources"]}}


def test_dhp7_the_off_schema_is_the_shipped_schema_byte_for_byte():
    """THE CONDITIONAL FORM'S WHOLE POINT. `_answer_tool()` with no argument must be the schema HEAD
    shipped -- key for key, order included -- or the "byte-identical when OFF" law is a promise instead of
    a property, and every control arm in G1/G2 stops being a control. Pinned as a LITERAL rather than
    against the function, because a pin that re-derives the expected value from the code under test
    asserts nothing."""
    assert an._answer_tool() == _SHIPPED_OFF_SCHEMA
    assert an._answer_tool(handles=False) == _SHIPPED_OFF_SCHEMA
    assert list(an._answer_tool()["input_schema"]["properties"]) == [
        "tldr", "mechanism", "diagram_mermaid", "sources"]


def test_dhp7_the_plan_property_is_added_first_optional_and_only_under_handles():
    """D-HP-7's FIFTH PROPERTY, and every clause of it that a later edit could quietly drop.

    FIRST, because reason-then-write is the point (a plan emitted after the prose is a rationalisation),
    and because the cost is PRE-REGISTERED: the planning region's tokens delay the first `tldr` delta, so
    D-HP-24's "TTFB unchanged at the transport" is false and D-HP-27/R5 owns the SSE consequence.
    NOT REQUIRED, because a turn that needs no scratchpad must not be forced to invent one.
    ONLY UNDER HANDLES, because the OFF arm must stay byte-identical and the DOSSIER lane calls with no
    arguments at all."""
    props = an._answer_tool(handles=True)["input_schema"]["properties"]
    req = an._answer_tool(handles=True)["input_schema"]["required"]
    assert list(props)[0] == "plan"                            # emitted FIRST
    assert props["plan"]["type"] == "string" and props["plan"]["description"]
    assert "plan" not in req                                   # ...never required
    assert "plan" not in an._answer_tool()["input_schema"]["properties"]
    assert "tldr" in req and "mechanism" in req


def test_dhp9_sources_is_dropped_from_properties_AND_from_required():
    """D-HP-9 / R1. `sources` is in BOTH `properties` and `required`, so a conditional that varied only
    one would emit a schema demanding a property it does not declare -- the folded C29/G24 finding. The
    deletion is what makes THREE killed classes unconstructible: `fabricated_citation` has no ledger row
    to mint, `ledger_cascade` goes with it, `undeclared_unsupported` collapses to an index-range check."""
    schema = an._answer_tool(handles=True)["input_schema"]
    assert "sources" not in schema["properties"]
    assert "sources" not in schema["required"]
    assert schema["required"] == ["tldr", "mechanism"]
    assert "sources" in an._answer_tool()["input_schema"]["required"]     # ...and the control keeps it


def test_dhp9_the_ledger_is_re_minted_from_resolved_after_verify_and_before_provenance():
    """D-HP-9 / R1's THIRD CONTRACT, the one with a READER-FACING cost. `resolved` survives the schema
    drop (verify mints it positionally), but `structured['sources']` does not -- and TWO consumers read
    THAT and nothing else: `_attach_provenance`, the SOLE producer of `source_key` and therefore the input
    to the 6.5 PDF click-to-page locator, and the FE's DURABLE `resolvedFor` path (a different function
    from the live path's `resolvedMap`). A drop without this costs receipts AND click-to-page.

    THE DIRECTION AND THE ORDER ARE BOTH THE CONTRACT (folded G17). FROM `resolved`, never the reverse:
    a ledger written BEFORE `verify_citations` makes `_match_ledger_entry` match by construction and
    `fabricated_citation` read 0 TAUTOLOGICALLY -- the gate measuring its own scaffolding. AFTER verify,
    BEFORE `_attach_provenance`."""
    src = _read("answer")
    assert src.count("        _synthesize_sources(structured, verifier)") == 2      # both bodies
    at = -1
    for _ in range(2):
        at = src.index("_synthesize_sources(structured, verifier)", at + 1)
        assert src.rindex("vf.verify_citations(", 0, at) < at                       # ...after verify
        assert at < src.index("_attach_provenance(structured, verifier)", at)       # ...before provenance
    # THE ROW SHAPE IS TODAY'S POST-`_attach_provenance` SHAPE, field for field, so every downstream
    # consumer joins unchanged and the stamp becomes an idempotent re-stamp rather than a no-op.
    st: dict = {"tldr": "t", "mechanism": "m"}
    rep = {"resolved": {"2": {"source": "USDA WASDE", "date": "2026-05-12",
                              "source_key": "s3://w", "snippet": "stocks fell"},
                        "1": {"source": "MPOB", "date": "2026-04-30",
                              "source_key": "s3://m", "snippet": "output rose"}}}
    assert an._synthesize_sources(st, rep) == 2
    # Phase F widened the row with the three span keys (char_start/char_end/offset_kind, None when the
    # resolved entry lacks them) -- additive, so the field-for-field claim above still holds on the
    # original five plus honest Nones.
    _f = {"char_start": None, "char_end": None, "offset_kind": None}
    assert st["sources"] == [
        {"ref": 1, "source": "MPOB", "date": "2026-04-30", "note": "output rose", "source_key": "s3://m", **_f},
        {"ref": 2, "source": "USDA WASDE", "date": "2026-05-12", "note": "stocks fell",
         "source_key": "s3://w", **_f}]
    an._attach_provenance(st, rep)                             # idempotent: the join is already total
    assert [r["source_key"] for r in st["sources"]] == ["s3://m", "s3://w"]
    assert an._synthesize_sources({"tldr": "t"}, {"resolved": {}}) == 0


def test_dhp16_the_document_lane_calls_the_tool_with_no_arguments():
    """D-HP-16, THE CLAUSE THAT MAKES THE DOSSIER'S SCHEMA HALF AVOIDABLE (correcting the draft's
    "unavoidable ... rides D-HP-9 by construction"). `dossier.py` shares `_answer_tool` deliberately --
    its own comment is "a bespoke schema is how a document quietly stops being verifiable" -- so the
    conditional form is exactly what keeps the document lane on typed prose until D-HP-28's own gate.
    The dossier has NO handle-render pass at all (`_resolve_number_handles` and friends have two call
    sites, both in answer.py), so a schema flip there would ship handle-only prose with nothing to
    render it."""
    src = _read("dossier")
    assert "_answer_tool()" in src
    assert "_answer_tool(handles" not in src and "_answer_tool(True)" not in src
    assert dos.SYNTH_MODEL                                     # ...the document lane is the live one
    assert an._answer_tool() == _SHIPPED_OFF_SCHEMA


# ══ D-HP-7 / D-HP-8 / D-HP-12 -- THE GRAMMAR: THE PROMPT SURFACE ═════════════════════════════════════

def test_dhp7_the_leg_is_appended_last_and_supersedes_the_four_spans_by_name():
    """D-HP-7's contract is a ONE-SIDED NARROWING of the shipped D-PQ contract ("value AND handle" ->
    "handle ONLY, in the slot"), and the plan's instruction is that the four spans stating the old rule
    are rewritten to say so. They are SUPERSEDED BY NAME in an APPENDED leg rather than edited in place --
    D-HP-8's recorded decision, because the in-place form is a `response_contracts.apply` needle job over
    three byte-pinned needles shared by every contract, which would make the D-HP arm inseparable from the
    contract selector and cost the OFF arm its byte-identity.

    AN APPENDED LEG THAT DOES NOT NAME WHAT IT OVERRIDES LEAVES THE MODEL HOLDING A CONTRADICTION. This
    pin asserts the contradiction is closed for each of the four, and that the leg lands LAST of the
    persona legs (it narrows every number rule above it) while `_rc.directive` stays the true tail."""
    on = an._system(handles=True)
    leg = an._SYSTEM_HANDLES
    assert on.endswith(leg) or leg in on
    # the leg is AFTER the provenance leg and BEFORE the response-contract emphasis (the fail-open pin)
    with_prov = an._system(handles=True, provenance=True)
    assert with_prov.index(an._SYSTEM_PROVENANCE) < with_prov.index(leg)
    # ...each superseded span is quoted back and cancelled
    assert "every figure you state MUST appear in an injected row" in leg   # (a) _SYSTEM_CASCADE
    assert "the FIGURE half is deleted" in leg
    assert "sources ledger" in leg and "there is no sources ledger on this turn" in leg   # (b) :288/:294
    assert "ORDER citations most-trusted first" in leg and "[T1]-[T4] trust tag" in leg   # (c) the tier rule
    # ...and the four spans it supersedes really are in the base persona it is appended to
    base = an._system()
    assert "every figure you state MUST appear in an injected row and carry its numbered [N] handle" in base
    assert "declared in the sources ledger" in base
    assert "ORDER citations most-trusted (lowest T) FIRST" in base


def test_dhp7_the_slot_grammar_and_the_size_zero_op_set_are_both_stated():
    """B1 AS RATIFIED, IN THE MODEL'S HEARING. The value slot is a syntactic locality cue that already
    ships (`_HANDLE_VALUE_SLOT_RX`: a value-introducing word immediately before the handle), so the leg
    teaches THE SHIPPED CUE rather than inventing a syntax -- the pin checks the leg's example words are
    ones the shipped regex actually recognises, or the prompt would be teaching a slot the renderer
    cannot see.

    AND THE OPERATOR WHITELIST IS SIZE ZERO, which after the R10 shown-bound re-run is a MEASUREMENT and
    not a decision: DERIVED numerals are 2.0% at 0.25x their own chance floor, falling to 1.3%/0.8% under
    shown-binding, and no op (sum, diff, ratio, pct_change, count_streak, share, minmax, agg) clears its
    floor in any variant. So the grammar is DIRECT + A REFUSAL, and the REFUSAL has to be stated as a
    legitimate move or the model fabricates instead of declining."""
    leg = an._SYSTEM_HANDLES
    slot_rx = an._HANDLE_VALUE_SLOT_RX
    for word in ("at", "of", "to", "was", "rose to", "settled at", "printed"):
        assert f"'{word}'" in leg
        # the cue is matched against the text IMMEDIATELY BEFORE the handle (the regex is anchored `\\s+$`),
        # so this asserts the renderer recognises the exact slots the prompt just taught
        assert slot_rx.search(f"stocks {word} "), word
    assert "NO ARITHMETIC" in leg
    for op in ("add", "subtract", "ratio", "average", "percent-change", "rank", "streak-count"):
        assert op in leg
    assert "Refusing a magnitude is a correct, professional move here" in leg
    # ...and the qualitative half stays FREE PROSE (it carries no digit; the lint never sees it)
    assert "'roughly half'" in leg and "'sharply lower'" in leg


def test_dhp7_the_leg_refuses_a_density_mandate_and_keeps_dates_writable():
    """TWO THINGS THE LEG MUST *NOT* SAY, each a measured failure mode.

    (1) NO DENSITY MANDATE (B7). Mandatory-citation grammars convert non-citation failures into
        MIS-citation failures -- the same clinical measurement that argued lever (ii) down to a control --
        and mis-citation IS this wave's #1 risk. Number-avoidance is caught instead by G1 clause (8)'s
        AGGREGATE band, checked after the fact, with no instruction to the writer.
    (2) DATES SURVIVE. D-HP-7 puts dates, era labels and delivery months OUT of scope for the first build,
        so a contract reading "never type a digit" would take the RECENCY discipline's dated claims down
        with it. The EXTRACTOR agrees, which is what makes this safe rather than merely intended: a bare
        calendar year, a year-range tail, a date's day, an ordinal and a duration modifier are all exempt
        from `verify._claim_number_spans`, so none of them is a magnitude to the lint either."""
    leg = an._SYSTEM_HANDLES
    assert "There is no minimum" in leg and "do not sprinkle handles to look grounded" in leg
    assert "may carry no handle at all" in leg
    for banned in ("at least one handle per", "every sentence must carry", "minimum of"):
        assert banned not in leg
    assert "dates, years, marketing years, delivery months" in leg
    for shape in ("the ban took effect 2010-08", "in MY 2021/22", "the 3rd consecutive month",
                  "a 5-year mean", "over 1998-99"):
        assert not vf._claim_number_spans(vf._mask_handles(shape)), shape


def test_dhp7_direction_stays_the_analysts_and_sign_is_never_typed():
    """D1, THE HALF D-HP DOES NOT MOVE. The engine prints MAGNITUDE, UNIT, DATE and CITATION; the analyst
    writes DIRECTION -- and NOT SIGN, because D-HP-11's splice writes `abs(value)` for sign-meaningful
    rows precisely so the verb keeps carrying it. A minus sign typed in front of a handle would be the
    model overwriting the one thing it still owns, and would print "fell to -0.31" on every signed-delta
    row. The verbs taught here are D-HP-13's licensed lexicon, so the prompt and the direction-vs-sign
    check cannot drift apart."""
    leg = an._SYSTEM_HANDLES
    assert "DIRECTION IS YOURS, MAGNITUDE IS THE ROW'S" in leg
    for verb in ("'fell'", "'rose'", "'widened'", "'tightened'", "'drew'"):
        assert verb in leg
    assert "Do NOT write a minus sign" in leg and "the word 'negative'" in leg


def test_dhp7_grouped_tokens_are_forbidden_in_a_value_slot_by_the_prompt_too():
    """D-HP-11's `grouped_in_slot` class, stated on the PROMPT side as well as charged on the render side.
    The docstring rule is that a grouped token NEVER receives the value splice ("it stands in for no
    single figure"), and TODAY that is harmless because the model also writes the digit. Under
    "handle ONLY, in the slot" it is not: a fully-RESOLVED `[N13, N14]` in a value slot is left untouched
    BY DESIGN and ships to the reader, re-minting the exact D-PQ HANDLE-1 defect that G1 clause (2) is
    blind to. Cheapest possible fence first -- tell the writer -- with the charge and the sever behind."""
    leg = an._SYSTEM_HANDLES
    assert "NEVER put a GROUPED or RANGED token" in leg and "[N13, N14]" in leg
    assert "a group stands in for no single figure" in leg
    assert "Group only when you are citing several items for one qualitative claim" in leg


def test_dhp12_the_prompt_exemption_is_exactly_the_lint_the_verifier_charges():
    """R3 OPTION (b) AS RATIFIED, PINNED ACROSS THE SEAM. The prompt promises ONE exemption -- a figure
    that exists only in an evidence item's quoted text may be typed IN THE SAME SENTENCE AS THAT ITEM'S
    [E] HANDLE -- and `verify.bare_digit_verdict` is what actually decides it. A prompt promising a
    narrower or wider exemption than the lint enforces is the D-PQ contract defect wearing a new hat: the
    model would either lose 850 real figures per corpus, or type numbers the lint then deletes.

    The exemption is SENTENCE-SCOPED and deliberately generous (it does not ask whether the [E] item
    carries the numeral -- that needs a span, which is option (a)); a generous exemption costs a COUNT,
    never a false deletion, which is D3."""
    leg = an._SYSTEM_HANDLES
    assert "THE ONE EXEMPTION" in leg and "IN THE SAME SENTENCE AS THAT ITEM'S [E] HANDLE" in leg
    assert "the engine deletes the sentence that carries it" in leg
    assert vf.bare_digit_verdict("The mill reported a 4.2% cut [E3].") == "e_cited"
    assert vf.bare_digit_verdict("Stocks fell 12.5 MMT.") == "bare_digit"
    assert vf.bare_digit_verdict("Stocks fell to 12.5 MMT [N4].") == "bare_digit"   # [N]-only never exempts
    assert vf.bare_digit_verdict("Stocks fell [N4].") is None                       # nothing typed
    assert vf.bare_digit_verdict("The balance tightened through 2021.") is None     # a year is not a claim


def test_dhp12_the_hard_counter_prices_the_exemption_on_the_treatment_lane_only():
    """R3(b)'s HARD COUNTER -- the number that decides whether option (a) (the `[Q]` span handle) is worth
    its own phase. `charged` is the class the ledger also carries under `by_rule['bare_digit']`; `e_cited`
    is the 10.5%-of-numerals hole option (b) knowingly leaves open. PRESENT ONLY ON THE TREATMENT LANE,
    the OFF-arm-clean rule: a key absent is honest, a key present and always zero is a column that says
    "measured" when nothing measured it."""
    st = {"tldr": "Stocks fell 12.5 MMT.", "mechanism": "The mill reported a 4.2% cut [E1]."}
    rep = vf.verify_citations(dict(st), [], handle_prose=True)
    assert rep["bare_digit"] == {"charged": 1, "e_cited": 1}
    assert "bare_digit" not in vf.verify_citations(dict(st), [])          # control: no such key


# ── D-HP-15: THE EPISODE PERSONA'S SELECT VARIANT, AND THE CONTROL PERSONA'S BYTE-IDENTITY ────────────

def test_dhp15_the_select_variant_is_appended_and_the_control_persona_is_byte_identical():
    """THE SELECT LEG IS APPENDED, NEVER AN IN-PLACE REWRITE of `_SYSTEM_EPISODES` -- the same shape
    `_SYSTEM_HANDLES` uses on the body, and for the same reason: the mandate is a module constant shared
    by EVERY turn, so an in-place edit would make the D-HP arm inseparable from the episode mandate and
    would cost the control arm its byte-identity.

    THE CONTROL IS BYTE-IDENTICAL, NOT MERELY SIMILAR (section 2's standing law), and it is asserted on
    the ASSEMBLED persona, both polarities of `episodes`, so a leg appended under the wrong conjunction
    cannot pass. The variant is meaningless without the mandate it narrows, so it rides `episodes AND
    handles` -- one conjunction, never two independent appends."""
    base_ep = an._system(episodes=True)
    assert an._system(episodes=True, handles=False) == base_ep            # OFF is byte-identical
    assert base_ep == an._system(episodes=False) + an._SYSTEM_EPISODES + ""  # ...the mandate ALONE
    treat = an._system(episodes=True, handles=True)
    assert an._SYSTEM_EPISODES_SELECT in treat
    assert an._SYSTEM_EPISODES_SELECT not in base_ep
    # the variant is inert without the mandate: no episodes, no select leg, on either polarity of handles
    assert an._SYSTEM_EPISODES_SELECT not in an._system(episodes=False, handles=True)
    # ...and the mandate still precedes it, so the model reads what is being narrowed first
    assert treat.index(an._SYSTEM_EPISODES) < treat.index(an._SYSTEM_EPISODES_SELECT)


def test_dhp15_the_select_leg_says_select_order_connect_and_narrows_only_selection():
    """WHAT THE LEG IS ALLOWED TO SAY, pinned so a later edit cannot quietly turn it into a second number
    contract (which is how a grammar acquires the contradiction D-HP-8 refused) or into an ORDER mandate
    (the model's order survives -- `eval._line_targets` matches order-insensitively, so nothing
    downstream reads bullet order as meaning).

    THE THREE CLAUSES: reference only the stamped windows VERBATIM; cite receipts by their [E] handles;
    type no magnitudes. Plus the fourth, which is a PERMISSION and not a rule: the connective prose is
    the model's."""
    leg = an._SYSTEM_EPISODES_SELECT
    assert "SELECT, ORDER, CONNECT" in leg
    assert "DELETED WHOLE" in leg                       # the remedy is stated in the model's hearing
    assert "[E] handle" in leg and "[N] handle" in leg
    assert "THE CONNECTIVE PROSE IS YOURS" in leg
    # it does NOT re-open the number contract in a second vocabulary, and it does not mandate an order
    for banned in ("SUPERSEDES", "chronological", "in date order", "oldest first"):
        assert banned not in leg


_SPAN_A_G = "1994-06..1994-08"                  # a `timeline.month_span` token, spelled as it is stamped
_SPAN_PARITY_CORPUS = (
    "- 1994-06..1994-08 -- drivers/frost: no citable item in this window.",
    "- 2019-01..2019-03 -- the great disruption: milder than the 1994-06..1994-08 frost [E1].",
    "- 1994-06..1994-08 and 2019-01..2019-03 -- twin frosts [E1]: no priced move.",
    "- 2021-06..2021-08 -- the mill reports damage [E1]; prices moved 3.5 percent, or 1.2 million bags.",
    "- 1994-06 .. 1994-08 -- respaced, so the scorer sees two windows and no span at all.",
    "- frost was bad in the 1990s, and the 2019 crop was thin: no citable item.",
    "- 1994-06-10..1994-08-01 -- the DAY-grain spelling, which is nobody's stamped token.",
    "prose with no bullet marker and no window in it at all",
    "",
)


def test_dhp15_the_span_shape_scanner_agrees_with_the_scorers_own_tokenization():
    """H1b FOLD-1 F1: THE SECOND SPELLING IS CHECKED, NOT TRUSTED. `answer` cannot import `eval` (the AST
    pin in test_ddt_scaffold_fork_basis), so `_EPISODE_SPAN_SHAPE_RX` is a second spelling of the
    tokenization `eval._line_targets` does with `_YM_RX` before its own string equality -- and a second
    spelling is how two readers come to disagree, which is why agreement is a cross-import TEST (the
    `_SCAFFOLD_ABSENCE_RX` idiom).

    THE DIRECTION THAT MUST NEVER HAPPEN is the scanner being NARROWER than the scorer: a 'YYYY-MM..
    YYYY-MM' the scorer can read but the fence cannot see is a fabricated window shipping uncharged,
    which is the whole of F1. So that direction is asserted away entirely -- every span the scorer's own
    regex can build from a line is found, WHOLE, inside exactly one token the scanner returns.

    THE OTHER DIRECTION IS DELIBERATELY OPEN AND IS PINNED AS SUCH: the scanner is WIDER, because
    boundary-broken shapes ('11994-06..1994-08') are exactly what fail-closed must still convict, and
    `_YM_RX` refuses them by construction. Narrower is a fabrication on the page; wider is a DROP, and
    the two are not symmetric.

    CORRECTED AT FOLD-2 (G-C): this docstring used to close "wider is a drop the scorer would not have
    credited either", AND THAT IS FALSE -- including for the respaced line in this very corpus, which
    `eval._line_targets` CREDITS (both endpoint months are `_YM_RX` hits) and the fence DROPS, and for
    '11994-06..1994-08', credited through its '1994-08' endpoint. THE TRUE STATEMENT: the fence can drop
    prose the scorer would have credited, the wave ACCEPTS that fail-closed loss, and the consequence --
    that a `min_episodes_cited` / `min_episode_lines` delta on the treatment arm is not purely the
    writer's -- is recorded at plan 10.13 for G2 to read rather than denied here."""
    ev_span = re.compile(ev._YM_RX.pattern + r"\.\." + ev._YM_RX.pattern)
    saw_any = False
    for line in _SPAN_PARITY_CORPUS:
        toks = an._episode_span_tokens(line)
        assert toks == an._EPISODE_SPAN_SHAPE_RX.findall(line)     # one scanner, one spelling
        for m in ev_span.finditer(line):
            saw_any = True
            hits = [t for t in toks if m.group(0) in t]
            assert len(hits) == 1, f"scorer sees {m.group(0)!r} in {line!r}; scanner returned {toks}"
        # ...and a token the scanner DID return never straddles a line the scorer reads as prose
        for t in toks:
            assert t in line and ".." in t
    assert saw_any, "a parity corpus that contains no span proves nothing"
    # THE WIDENING, PINNED: boundary-broken and non-calendar shapes are span-SHAPED here and are not
    # spans to `_YM_RX` at all -- which is why they are convicted rather than silently matched.
    for wide in ("11994-06..1994-08", "1994-06..1994-08..2025-01", "994-06..1994-08", "94-06..94-08"):
        assert an._episode_span_tokens(f"- {wide} -- frost [E7]") == [wide]
        assert ev_span.search(wide) is None or ev_span.search(wide).group(0) != wide
    # ...and an ordinary decimal is NOT span-shaped, which is what keeps the fence off connective prose
    for not_a_span in ("3.5", "1.2 million bags", "up 0.4pp", "2021-07-20", "-- a dash clause --"):
        assert an._episode_span_tokens(f"- {_SPAN_A_G} -- frost {not_a_span} [E1].") == [_SPAN_A_G]


# ══ D-HP-8 -- THE TREATMENT BUNDLE IS ONE RESOLUTION, THREADED ═══════════════════════════════════════

def test_dhp8_one_resolution_reaches_all_four_seams_on_both_bodies():
    """B8's BUNDLE RULE, asserted at the seam rather than in prose. The prompt contract (D-HP-7), the tool
    schema (D-HP-9), the verifier's charge + positional [E] resolution (D-HP-9/12) and the render passes
    (D-HP-10/11) move TOGETHER -- two knobs would re-create the GRAPHRAG_VERIFY_ALLNUM hazard PHASE9_B
    deliberately refused, and section 2's standing law is that a flag gating a strip rule which can differ
    across arms makes the arm measure its own instrument.

    ONE LOCAL READ PER BODY IS HOW THAT IS GUARANTEED rather than promised, and it must be on BOTH bodies:
    `GRAPHRAG_PLANNER=onehop` is the DOCUMENTED rollback lane, and D-HP-16 is explicit that a one-lane
    landing restores the D2 asymmetry on exactly the path a rollback puts every turn on."""
    src = _read("answer")
    assert src.count("_handles = _handle_prose_active(mode_knobs)") == 2   # ONE read per body
    assert src.count("_answer_tool(handles=_handles)") == 2                # the tool schema, both bodies
    # >= 4 = the two schema call sites + the two `_system(..., handles=_handles)` persona sites; the
    # render passes (D-HP-10/11) thread the SAME local and may add more, which is the bundle working.
    assert src.count("handles=_handles") >= 4
    # THE VERIFIER SEAM IS PINNED PER CALL SITE, not by a global count: `handle_prose=` must be the SAME
    # local `_handles` at both `verify_citations` calls, never a second derivation.
    at = -1
    for _ in range(2):
        at = src.index("vf.verify_citations(", at + 1)
        assert "handle_prose=_handles" in src[at:at + 400]
    assert src.count("vf.verify_citations(") == 2
    # ...and NOTHING re-derives the bundle: no serving body calls the raw knob resolver at all -- both
    # read `_handle_prose_active`, which is now a thin env-reading wrapper over the LEAF's one resolution
    # (H1 FIX Z9/Z12). The pin moves from "called once" to "called by nobody but the wrapper", which is
    # the stronger form of the same property.
    assert src.count("_handle_prose_on(mode_knobs)") == 0
    assert "def _handle_prose_active" in src
    assert "_rm.handle_prose_active(" in src               # the ONE resolution, in the leaf
    assert "_rm.handle_prose_on(mode_knobs" in src         # ...and the kill spellings with it


def _one_contract_graph():
    """The smallest real `CausalGraph` a serving body will walk -- built here rather than imported from a
    sibling test file, so this suite stays the grammar's contract and nothing else's."""
    from leviathan.causal import schema as cs
    from leviathan.graphrag import graph as g
    c = cs.CausalContract(
        contract="arabica_coffee", aliases=["arabica"],
        drivers=[cs.Driver(id="frost", type="hazard", sign="+", mechanism="frost kills trees")],
        convergence=[cs.ConvergenceSignal(name="arabica_squeeze", direction="+", requires_any_n_of=1,
                                          drivers=["frost"])])
    return g.CausalGraph({"arabica_coffee": c}, silver=set())


def test_dhp7_the_whole_bundle_end_to_end_control_versus_treatment():
    """THE WAVE'S CENTRAL CLAIM, ASSERTED THROUGH A REAL SERVING BODY RATHER THAN AT FOUR SEPARATE SEAMS.
    Same query, same fixture, same draft -- ONE variable, the `deep_hp` knob dict -- and every half of the
    bundle is read off the OUTSIDE: the schema the model was handed, the persona it was given, what the
    server did with its scratchpad, and what the reader ends up with.

    THIS IS THE PIN THAT WOULD HAVE CAUGHT A HALF-LANDED D-HP-9. `sources` is dropped from the schema, so
    the treatment turn's ledger can only come from `resolved` -- and if the re-synthesis were missing, the
    assertions below would show an EMPTY ledger with a POPULATED `resolved`, i.e. the reader losing
    receipts and 6.5 click-to-page while every other clause still passed.

    Run on the ONE-HOP body deliberately: it is the DOCUMENTED `GRAPHRAG_PLANNER=onehop` rollback lane,
    the one D-HP-16 says a one-lane landing breaks, and the one whose seams are easiest to land only in
    the L2 body by accident."""
    import leviathan.graphrag.reasoning_modes as rm
    seen: dict = {}

    def fake_call(system, user, *, model, tool, **kw):
        seen["system"] = system if isinstance(system, str) else "".join(map(str, system))
        seen["tool"] = tool
        return {"tldr": "Stocks fell to [E1].", "diagram_mermaid": "", "sources": [],
                "mechanism": "## Mechanism\nThe crop is short [E1]. Output was 12.5 MMT.",
                "plan": "cite E1. 12.5 vs 14.9 -- do not type either."}

    def fake_retrieve(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{node}",
                 "text": "the crop is short after frost"}]

    def _run(knobs):
        return an.answer("frost in arabica", graph=_one_contract_graph(), planner="onehop",
                         asof="2021-08-01", retrieve=fake_retrieve, call=fake_call,
                         route_fn=lambda q, gg: ["arabica_coffee"], mode_knobs=knobs)

    ctl = _run(rm.knobs("deep"))
    ctl_schema, ctl_system = seen["tool"]["input_schema"], seen["system"]
    trt = _run(rm.knobs("deep_hp"))
    trt_schema, trt_system = seen["tool"]["input_schema"], seen["system"]

    # (1) THE SCHEMA the model was handed
    assert ctl_schema["required"] == ["tldr", "mechanism", "sources"]
    assert trt_schema["required"] == ["tldr", "mechanism"] and "plan" in trt_schema["properties"]
    # (2) THE PERSONA it was given
    assert "HANDLE-PROSE" not in ctl_system and "HANDLE-PROSE" in trt_system
    # (3) THE SCRATCHPAD never reaches `structured` on either arm (the property is simply absent on the
    #     control, and popped on the treatment) -- so it can never reach the judge or the FE.
    assert "plan" not in ctl["structured"] and "plan" not in trt["structured"]
    # (4) THE LEDGER: minted from `resolved`, carrying `source_key`, on the treatment arm ONLY.
    assert ctl["structured"]["sources"] == []                  # the model authored none; unchanged
    assert [r["ref"] for r in trt["structured"]["sources"]] == [1]
    assert trt["structured"]["sources"][0]["source_key"] == "s3://arabica_coffee"
    assert trt["trace"]["citation_verifier"]["resolved"]["1"]["source"] == "GAIN"
    # (5) THE DIGIT-LINT: charged and REMEDIED on the treatment arm; untouched on the control.
    assert trt["trace"]["citation_verifier"]["bare_digit"]["charged"] == 1
    assert "bare_digit" not in ctl["trace"]["citation_verifier"]
    assert "12.5 MMT" in ctl["answer"] and "12.5 MMT" not in trt["answer"]
    # (6) ...and the treatment arm cannot mint the classes the schema deletion removes.
    for killed in ("fabricated_citation", "ledger_cascade", "undeclared_unsupported"):
        assert trt["trace"]["citation_verifier"]["by_rule"].get(killed, 0) == 0


def test_dhp16_the_onehop_rollback_lane_gets_a_ledger_and_the_off_arm_prompt_is_unchanged():
    """D-HP-16's SECOND REQUIREMENT, and the one a single-body landing quietly skips. The one-hop body has
    NEVER carried a GROUNDING LEDGER line (its own comment states it as a standing fact), which was fine
    while handles were optional decoration on typed prose. Under handle-ONLY prose it is the D2 asymmetry
    restored on the DOCUMENTED rollback lane: a NUMBERED menu with no statement of which addresses exist.

    AND THE OFF ARM MUST NOT MOVE. The line is gated on `_handles`, so a control turn's prompt is
    byte-identical -- asserted here as BYTES, at the real seam, not as a promise in a comment."""
    import leviathan.graphrag.reasoning_modes as rm
    seen: dict = {}

    def fake_call(system, user, *, model, tool, **kw):
        seen["user"] = user if isinstance(user, str) else "\n\n".join(map(str, user))
        return {"tldr": "t", "mechanism": "m", "diagram_mermaid": "", "sources": []}

    def fake_retrieve(q, node, *, k, asof=None, near=None):
        return [{"date": "2021-07-20", "source": "GAIN", "source_key": f"s3://{node}", "text": "a row"}]

    def _prompt(knobs):
        an.answer("frost in arabica", graph=_one_contract_graph(), planner="onehop", asof="2021-08-01",
                  retrieve=fake_retrieve, call=fake_call, route_fn=lambda q, gg: ["arabica_coffee"],
                  mode_knobs=knobs)
        return seen["user"]

    ctl, trt = _prompt(rm.knobs("deep")), _prompt(rm.knobs("deep_hp"))
    assert "GROUNDING LEDGER" not in ctl                       # the OFF arm is byte-identical...
    assert "GROUNDING LEDGER" in trt                           # ...and the treatment lane is addressable
    assert "[E] handles run [E1]..[E1]" in trt
    assert trt.replace("\n\n" + trt[trt.index("GROUNDING LEDGER"):].split("\n\n")[0], "") == ctl


def test_dhp8_the_enabling_lever_is_a_preset_and_the_env_is_one_way(monkeypatch):
    """R9's control surface, read from THIS side of the seam. The knob dict is what the escalation seam
    swaps WHOLE ("never a merge"), so the resolver takes the knob dict and never a mode name; and
    `GRAPHRAG_HANDLE_PROSE` can only ever turn the bundle OFF -- an env that could turn it ON would drift
    a gate arm and could stamp an arm nothing ran."""
    import leviathan.graphrag.reasoning_modes as rm
    assert an._handle_prose_active(rm.knobs("deep_hp")) is True
    assert an._handle_prose_active(rm.knobs("deep")) is False
    assert an._handle_prose_active(None) is False
    for on_ish in ("on", "1", "true", "yes"):
        monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", on_ish)
        assert an._handle_prose_active(rm.knobs("deep")) is False, on_ish   # cannot turn it ON
    for kill in an._HANDLE_PROSE_KILL:
        monkeypatch.setenv("GRAPHRAG_HANDLE_PROSE", kill)
        assert an._handle_prose_active(rm.knobs("deep_hp")) is False, kill  # ...only OFF


# ══════════════════════════════════════════════════════════════════════════════════════════════════════
# H1 ADVERSARIAL-REVIEW FIXES Z7 + Z10 -- the artifact whitelist and the streaming seam
# ══════════════════════════════════════════════════════════════════════════════════════════════════════

def test_z7_the_r3b_hard_counter_reaches_a_rendered_record():
    """FIX Z7. `eval._per_answer_record` is a HARD WHITELIST over the verifier report -- its own docstring
    says "a trace key not named here reaches NO artifact" -- and `report['bare_digit']` was absent from
    it. That dict is R3(b)'s HARD COUNTER: the STATUS block ratified option (b) on it, and R3 states it is
    the number that "decides whether option (a) is worth a phase". It was unreadable from any G1 run.

    NOTHING ELSE CARRIES IT. `emf.bare_digit_escapes` reads `trace.bare_digit_count` (D-HP-4(c)'s
    always-on typed-magnitude total, a different quantity) and `bare_digit_strips` reads
    `by_rule['bare_digit']` -- the CHARGED half only. `e_cited` had no reader at all."""
    tr = {"citation_verifier": {"enabled": True, "stripped": 3, "claim_count": 20, "checked": 4,
                                "by_rule": {"bare_digit": 3},
                                "bare_digit": {"charged": 3, "e_cited": 7}},
          "bare_digit_count": 9}
    row = {"q": {"id": "r1"}, "rubric": {}, "out": {"trace": tr}}
    rec = ev._per_answer_record(row, "single")
    assert rec["bare_digit"] == {"charged": 3, "e_cited": 7}
    # ...and it POOLS, so the R3 decision is readable off a G1 artifact with nothing re-run
    tot = ev._baseline_json([row], run_kind="single", model="m", judged=False, eval_set="s",
                            graph_version="v", corpus_fp="f", mode="deep_hp")["dhp_successor"]
    assert tot["bare_digit_strips"] == 3 and tot["bare_digit_e_cited"] == 7
    # CONTROL ROWS ARE CLEAN: verify mints the key on the treatment lane only, so the column is None
    ctrl = {"q": {"id": "r0"}, "rubric": {},
            "out": {"trace": {"citation_verifier": {"enabled": True, "by_rule": {}}}}}
    assert ev._per_answer_record(ctrl, "single")["bare_digit"] is None


def test_w2_the_slot_orphan_census_and_its_ledger_class_both_reach_a_rendered_record():
    """H1 FIX W2 -- FINDING NF-2, THE ARTIFACT HALF. The Z4/W1 pass DELETES SENTENCES and was invisible to
    every artifact: `slot_orphan_dropped` was in no registry (and `tracekeys` states its own contract --
    "a trace key not named here reaches no artifact"), and the deletions were in no `by_rule` class. A G2
    fluency delta caused by it would have had no readable cause in any G1/G2 run.

    BOTH HALVES REACH A ROW: the per-turn census as its own registered column (the registry's tail, per
    the append law), and the pooled magnitude as a ledger class inside `by_rule`, which is the location
    the class scan, the successor family and the EMF counters already read."""
    tr = {"citation_verifier": {"enabled": True, "stripped": 3, "claim_count": 20, "checked": 4,
                                "by_rule": {"index_out_of_range": 2, "slot_orphan": 1}},
          "slot_orphan_dropped": {"sentences_dropped": 1}}
    rec = ev._per_answer_record({"q": {"id": "r1"}, "rubric": {}, "out": {"trace": tr}}, "single")
    assert rec["slot_orphan_dropped"] == {"sentences_dropped": 1}
    assert rec["by_rule"]["slot_orphan"] == 1 and rec["strips"] == 3
    assert sum(rec["by_rule"].values()) == rec["strips"]          # the ledger's own invariant, on the row
    # CONTROL ROWS ARE CLEAN: the pass is treatment-gated, so the column is absent-as-None and the class
    # never appears -- which is what makes the arm comparison readable at all.
    ctrl = {"q": {"id": "r0"}, "rubric": {},
            "out": {"trace": {"citation_verifier": {"enabled": True, "stripped": 0, "by_rule": {}}}}}
    crec = ev._per_answer_record(ctrl, "single")
    assert crec["slot_orphan_dropped"] is None and crec["by_rule"] == {}


def test_w3_a_non_string_plan_value_is_suppressed_as_VALID_json():
    """H1 FIX W3 -- FINDING NF-3. The string path forwards the value's own quotes, so the draft reads
    `"plan": ""` and stays PARSEABLE -- which is the property Z10's rationale rests on (the FE parses the
    accumulated draft and only falls back to a per-key regex scrape when that throws). The DEFENSIVE
    non-string path forwarded nothing at all, emitting `{"plan": , "tldr": ...}`: invalid JSON, i.e. the
    branch that exists to degrade gracefully degraded WORSE than the one it mirrors.

    It now emits the literal `null`. The suppression itself was never in doubt and is re-pinned here: no
    branch of this filter may let plan CONTENT through."""
    import json as _json
    for doc, leak in ((_json.dumps({"plan": {"a": "nested 999"}, "tldr": "A.", "mechanism": "B."}), "999"),
                      (_json.dumps({"plan": 12345, "tldr": "A.", "mechanism": "B."}), "12345"),
                      (_json.dumps({"plan": None, "tldr": "A.", "mechanism": "B."}), None),
                      (_json.dumps({"plan": True, "tldr": "A.", "mechanism": "B."}), None),
                      (_json.dumps({"plan": ["a 777", "b"], "tldr": "A.", "mechanism": "B."}), "777")):
        for width in (1, 3, 7, 1000):
            seen: list[str] = []
            relay = an._plan_filtered_token_relay(seen.append)
            for i in range(0, len(doc), width):
                relay(doc[i:i + width])
            got = "".join(seen)
            obj = _json.loads(got)                      # THE FIX: this raised ValueError before W3
            assert obj["plan"] is None, (doc, width, got)
            assert obj["tldr"] == "A." and obj["mechanism"] == "B.", (doc, width, got)
            if leak:
                assert leak not in got, (doc, width, got)
    # ...and the STRING path is untouched: it still renders as "" and still keeps its siblings byte-intact
    seen = []
    relay = an._plan_filtered_token_relay(seen.append)
    relay('{"plan": "corn 12.5", "tldr": "A.", "mechanism": "B."}')
    assert _json.loads("".join(seen)) == {"plan": "", "tldr": "A.", "mechanism": "B."}


def test_z10_the_plan_region_never_reaches_the_sse_token_stage():
    """FIX Z10. `_pop_plan` deletes the planning region server-side AFTER the model call returns, which
    cannot unsend what the SSE `token` stage already delivered: the forced-tool relay forwards the raw
    `input_json_delta` of the tool input AS IT GENERATES, and `plan` is emitted FIRST in the schema. So
    the whole region reached the browser and sat in React state before anything verified it -- while
    `_PLAN_PROPERTY_DESC` tells the model that region is "not shown to the reader, not stored" and to
    "Write numbers here freely". The one place the model is instructed to type unverified, unlinted,
    unstripped magnitudes was the one region shipped to the client unfiltered.

    THE FILTER IS AT THE RELAY AND IT IS SERVER-SIDE (R5(b)). What survives is the key and the value's
    own quotes, so the accumulated draft stays parseable JSON and the FE's partial-JSON scrape of
    tldr/mechanism is untouched."""
    seen: list[str] = []
    relay = an._plan_filtered_token_relay(seen.append)
    # ONE document, delivered in the awkward fragments a real stream produces (mid-key, mid-escape).
    for chunk in ('{"pl', 'an": "corn stocks are 1', '2.5 mil bu and I think the ', 'ratio is 0.084',
                  '", "tldr": "Stocks tigh', 'tened [N1].", "mechanism": "Use ', 'ran ahead [N2]."}'):
        relay(chunk)
    got = "".join(seen)
    for leaked in ("corn stocks are", "12.5 mil bu", "0.084", "I think"):
        assert leaked not in got, f"the plan region reached the token stage: {leaked}"
    assert "Stocks tightened [N1]." in got and "Use ran ahead [N2]." in got
    import json as _json
    assert _json.loads(got) == {"plan": "", "tldr": "Stocks tightened [N1].",
                                "mechanism": "Use ran ahead [N2]."}


def test_z10_an_escaped_quote_inside_the_plan_cannot_end_the_suppression():
    """The scanner is a STATE MACHINE and not a regex for exactly this: a `\\"` inside the plan string
    would close the value to a naive reader and leak everything after it."""
    seen: list[str] = []
    relay = an._plan_filtered_token_relay(seen.append)
    relay('{"plan": "he said \\"12.5\\" and then 0.084", "tldr": "ok [N1]."}')
    got = "".join(seen)
    assert "12.5" not in got and "0.084" not in got and "he said" not in got
    assert "ok [N1]." in got


def test_z10_the_control_arm_relay_is_the_shipped_lambda_and_the_filter_is_a_pure_passthrough():
    """The CONTROL arm has no `plan` property, so it must not be wrapped at all -- byte-identical, not
    merely equivalent. And even if it were, the filter forwards a plan-free document unchanged."""
    src = _read("answer")
    assert 'on_token = (lambda t: _emit(on_stage, "token", text=t)) if on_stage is not None else None' in src
    assert "if _handles:\n        on_token = _plan_filtered_token_relay(on_token)" in src
    seen: list[str] = []
    relay = an._plan_filtered_token_relay(seen.append)
    doc = '{"tldr": "Stocks fell [N1].", "mechanism": "Use rose [N2]."}'
    for i in range(0, len(doc), 7):
        relay(doc[i:i + 7])
    assert "".join(seen) == doc
    assert an._plan_filtered_token_relay(None) is None


# == D-HP G1 AMENDMENT (2026-08-14) -- THE VOID'S FOUR ITEMS =========================================
# G1 decision 1 was VOIDED under clause (5): two treatment rows died at the shared 6000 max_tokens
# ceiling. The diagnosis proved the cause ARCHITECTURAL rather than a verbose writer -- the popped `plan`
# region took ~47% of treatment output (767 / 1,651 / 1,529 / 3,748 tokens over the four surviving rows),
# was ANTI-correlated with the retained prose (r = -0.28, i.e. plan and answer are SUBSTITUTES), and both
# prompt sites told the writer the region was free. The four items are pinned here, one test each.

def test_a1_the_turn_default_is_12000_on_every_mode_and_reaches_both_call_paths():
    """A1. The ceiling is a SHARED default (`max_tokens or 12000` in `_call_opus`), raised for EVERY mode
    including deep, and it must reach BOTH lanes: the SSE lane (`on_token` set -> serving_call_stream)
    and the BUFFERED lane the eval and POST paths take (`on_token` None -> serving_call). A ceiling that
    reached only one of them would raise the arm that was not truncating and leave the one that was.

    A HANDLES-GATED ceiling is REFUSED by the same reasoning: threading a treatment-only max_tokens would
    add a SECOND difference between the G1 arms and weaken the comparison the raise exists to rescue. And
    the DOCUMENT lane keeps its own: `dossier.SYNTH_MAX_TOKENS` is 16000, forwarded when provided."""
    from leviathan.graphrag import extract as ex
    from leviathan.graphrag import providers as pv
    src = _read("answer")
    assert "max_tokens=max_tokens or 12000" in src and "max_tokens or 6000" not in src
    seen: dict[str, list[int]] = {"buffered": [], "streamed": []}

    def _rec(kind):
        def go(client, system, user, **kw):
            seen[kind].append(kw["max_tokens"])
            kw["usage_sink"].append(ex.Usage(input_tokens=1, output_tokens=1))
            return {"tldr": "x"}, None
        return go

    def _rec_stream(client, system, user, *, on_token, **kw):
        return _rec("streamed")(client, system, user, **kw)

    _saved = (pv.make_client, pv.serving_call, pv.serving_call_stream)
    try:
        pv.make_client = lambda: object()
        pv.serving_call, pv.serving_call_stream = _rec("buffered"), _rec_stream
        kw = dict(model="claude-sonnet-4-6", tool={"name": "emit_answer"})
        an._call_opus("s", "u", **kw)                              # eval / POST -- BUFFERED
        an._call_opus("s", "u", on_token=lambda t: None, **kw)     # serving SSE -- STREAMED
        an._call_opus("s", "u", max_tokens=16000, **kw)            # the document lane's own ceiling
    finally:
        pv.make_client, pv.serving_call, pv.serving_call_stream = _saved
    assert seen["buffered"] == [12000, 16000]      # the default, then the caller's explicit override
    assert seen["streamed"] == [12000]
    assert dos.SYNTH_MAX_TOKENS == 16000           # ...unchanged; the document scale is its own
    # 16,000 is the HARD upper bound on the BUFFERED lane (the SDK's HTTP timeout becomes the failure
    # mode beyond it), so the shared default must sit strictly inside the safe non-streaming band.
    assert 6000 < 12000 < dos.SYNTH_MAX_TOKENS


def test_a2_both_plan_prompt_sites_carry_the_budget_and_the_off_arm_is_byte_identical():
    """A2. The false economy is corrected in BOTH places that instruct the region, because they are read
    in the SAME turn: a budget stated in the schema description and contradicted by silence in the
    persona is not a budget. "Digits cost nothing" was true of the LINT and false of the CEILING.

    AND THE OFF ARM DOES NOT MOVE. `plan` exists only under `_answer_tool(handles=True)` and the closing
    paragraph only under `_system(handles=True)`, so the control schema, the control persona in every
    permutation, and the DOCUMENT lane (`dossier.py` calls `_answer_tool()` bare) are byte-identical --
    D-HP-16's "SHIPS CONDITIONALLY OR IT DOES NOT SHIP", measured rather than asserted."""
    import itertools
    desc = an._answer_tool(handles=True)["input_schema"]["properties"]["plan"]["description"]
    leg = an._SYSTEM_HANDLES
    for probe in ("BUDGET IT AT ABOUT 800 TOKENS", "ONE output budget", "SUBSTITUTES",
                  "soft budget, not a hard limit"):
        assert probe in desc, probe
    for probe in ("KEEP IT SHORT", "about 800 tokens", "share ONE output budget",
                  "a long plan is a short answer"):
        assert probe in leg, probe
    # the corrected half survives in both: the LINT never charges a digit here, the CEILING always does
    assert "charged by the lint" in desc and "charged by the lint" in leg
    assert "this is the one place digits cost nothing" not in desc + leg
    # ...and the OFF arm carries none of it, on any persona permutation
    for outlook, episodes, recency, prov in itertools.product([False, True], [None, False, True],
                                                              [False, True], [False, True]):
        off = an._system(outlook=outlook, episodes=episodes, recency=recency, provenance=prov)
        assert "800 tokens" not in off and "THINK IN `plan`" not in off
    assert an._answer_tool() == an._answer_tool(handles=False) == _SHIPPED_OFF_SCHEMA
    assert "plan" not in an._answer_tool()["input_schema"]["properties"]


def test_a3_plan_tokens_is_a_count_never_the_text_and_is_absent_on_control():
    """A3. The region was unmeasurable BY CONSTRUCTION -- popped server-side, stripped from the SSE relay
    -- so G1's void had to be diagnosed by regression against a control arm. The remedy is a SCALAR and
    only a scalar: `_pop_plan`'s privacy reason (a trace key would put the model's private reasoning into
    a stored artifact the judge, the adjudicators and the FE all read) is unchanged and is RESTATED at
    the new field. Absent on every control row, because `plan` is not in the control schema at all."""
    import pathlib as _pl
    assert an._plan_tokens(None) is None and an._plan_tokens("") is None and an._plan_tokens("   ") is None
    assert an._plan_tokens("a" * 3200) == 800          # chars/4, the stated estimator
    assert an._plan_tokens("x") == 1                   # ...floored at 1, never 0 for a non-empty region
    trt = {"tldr": "a", "mechanism": "b", "plan": "cite N1 then N2. 12.5 vs 14.9."}
    ctl = {"tldr": "a", "mechanism": "b", "sources": []}
    assert an._plan_tokens(an._pop_plan(dict(ctl))) is None            # CONTROL: no region, no column
    assert an._plan_tokens(an._pop_plan(dict(trt))) == 8
    popped = dict(trt)
    an._pop_plan(popped)
    assert "plan" not in popped                        # the TEXT is still dropped on the floor
    src = _read("answer")
    assert src.count('"plan_tokens": _plan_tok') == 2                  # BOTH serving bodies
    assert "plan_tokens" in tk.TRACE_RECORD_KEYS       # registration IS the lift (the C2/U3 class)
    # the column carries a COUNT: no consumer may extend it to a prefix, a sample or the region's bytes
    assert "NEVER THE TEXT" in _pl.Path(tk.__file__).read_text(encoding="utf-8")
    assert "COUNT, NEVER THE TEXT" in " ".join(an._plan_tokens.__doc__.split())


def test_a4_a_truncated_turn_records_what_it_billed_on_both_lanes():
    """A4. TRUNCATION WAS AN EVIDENCE-DESTROYING FAILURE: both guards raised BEFORE `_usage_from` ran, so
    a dead row discarded the usage object together with the partial draft. G1's two dead rows burned
    2 x 6000 output tokens ($0.180) that no artifact could see -- `synth_spend_floor_usd` sums the rows
    that SURVIVED. The usage is now read first and travels on the exception AND in its message, because
    `str(e)` is what eval.py persists into `trace['error']`, a registered column a dead row does carry.

    RAISE BEHAVIOUR UNCHANGED, which is the constraint: same ValueError type, same trigger, same message
    prefix, still outside providers.RETRYABLE so nothing retries or degrades on a correctness failure."""
    import types

    from leviathan.graphrag import extract as ex
    from leviathan.graphrag import providers as pv
    _u = types.SimpleNamespace(input_tokens=41234, output_tokens=12000,
                               cache_creation_input_tokens=0, cache_read_input_tokens=38000)
    _resp = types.SimpleNamespace(stop_reason="max_tokens", content=[], usage=_u)
    _client = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: _resp))

    class _Stream:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(())

        def get_final_message(self):
            return _resp

    _sclient = types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **kw: _Stream()))
    lanes = ((ex.call_opus, _client, "switch this call to streaming"),
             (lambda *a, **k: ex.call_opus_stream(*a, on_token=None, **k), _sclient, "raise max_tokens"))
    for call, client, tail in lanes:
        with pytest.raises(ValueError) as ei:
            call(client, "sys", "user", model="claude-sonnet-4-6", max_tokens=12000)
        e = ei.value
        assert str(e).startswith("output truncated at max_tokens=12000 (stop_reason=max_tokens); ")
        assert tail in str(e)
        assert "billed in=41234 out=12000 cache_read=38000 cache_write=0" in str(e)
        assert e.usage.output_tokens == 12000 and e.usage.cache_read == 38000
        assert e.cost_usd == pytest.approx(0.315102)
        assert len(str(e)) < 300                   # ...must survive eval.py's `str(e)[:300]` clip whole
        assert not isinstance(e, pv.RETRYABLE)     # a correctness failure never retries or degrades
    # an UNPRICED model (a Bedrock inference-profile id) OMITS the cost rather than fabricating one:
    # `price()` falls back to Opus, which would overstate a Sonnet turn several-fold.
    with pytest.raises(ValueError) as ei:
        ex.call_opus(_client, "sys", "user", model="global.anthropic.claude-sonnet-4-6", max_tokens=12000)
    assert ei.value.cost_usd is None and "cost_usd=" not in str(ei.value)
    assert "billed in=41234 out=12000" in str(ei.value)       # ...the MEASURED counts still land


# == D-HP G1 REMEDIATION (2026-08-14) -- THE PROMPT HALVES OF THE TWO FAILED CLAUSES ===================
#
# D1 (clause 2): the 27 treatment + 28 control `unresolvable` events are NOT invented indices. Every one
# is an IN-RANGE menu row that came back EMPTY (`citations._empty_label` -> "NO ROWS RETURNED"), cited by
# the model as the RECEIPT FOR THE GAP after the prompt told it to state the gap. The GROUNDING LEDGER's
# range was already correct and is not the defect; nothing said an empty row is not addressable. Fixed in
# TWO halves, one per arm, same rule -- the persona for the treatment, the D-PQ EMPTY-1 scope note (the
# ONE existing producer, prompt-only, fires only on a turn that HAS an empty read) for both arms on the
# HYBRID lane only (`_numbers_block` is a `run_hybrid` producer; it does not reach the pure lanes --
# which costs the measured population nothing, all 55 empty rows being hybrid numbers-agent lookups),
# because the defect is on the shipped product and predates the wave.
# D2 (clause 2b): the persona never said the value slot belongs to [N] alone. Plan record: 10.18.

def _persona_off_permutations() -> list:
    """Every OFF-arm persona shape a serving turn can take. `handles=False` is the control arm."""
    return [an._system(),
            an._system(episodes=True), an._system(episodes=True, recency=True),
            an._system(outlook=True), an._system(provenance=True),
            an._system(episodes=True, outlook=True, recency=True, provenance=True)]


def test_d1_an_empty_menu_row_is_not_an_address_on_the_treatment_persona():
    """THE TREATMENT HALF. It sits with the paragraph it narrows ("ONE HANDLE, ONE FIGURE, AND CHECK THE
    ROW YOU ARE POINTING AT") and it names the GROUPED shape explicitly, because every measured event was
    a group or range standing in for the absence (`[N7, N8, N11, N12]`, `[N15-N17]`)."""
    hp = an._system(handles=True, episodes=True)
    assert "AN EMPTY MENU ROW IS NOT AN ADDRESS" in hp
    assert "NEVER write the handle of a row whose value reads NO ROWS RETURNED" in hp
    assert "not inside a group or range of handles" in hp
    assert hp.index("ONE HANDLE, ONE FIGURE") < hp.index("AN EMPTY MENU ROW IS NOT AN ADDRESS")
    for off in _persona_off_permutations():
        assert "AN EMPTY MENU ROW IS NOT AN ADDRESS" not in off
        assert "NO ROWS RETURNED" not in off


def test_d1_the_shared_empty_read_directive_carries_the_handle_clause_on_both_arms():
    """THE ARM-SYMMETRIC HALF, AND ITS FENCE. `orchestrator._numbers_block` is the ONE producer of the
    empty-read directive; it is PROMPT-ONLY (the reader-facing half stays `citations._empty_label`'s FACT,
    per that function's own split) and it fires ONLY when a call actually came back empty -- so a turn
    with no empty read is byte-identical on both arms, which is what makes a control-prompt change
    affordable at all."""
    full = {"query": {"table": "silver_wasde", "metric": "production", "commodity": "corn"},
            "status": "ok", "rows": [{"value": 1536.0, "unit": "1000 MT", "knowledge_date": "2026-06-01"}]}
    empty = {"query": {"table": "silver_wasde", "metric": "area", "commodity": "corn"},
             "status": "not_known", "rows": []}
    with_gap = orc._numbers_block([full, empty])
    assert "Do NOT cite the empty row's [N] handle" in with_gap
    assert "not inside a group or range of handles as the receipt for the gap" in with_gap
    assert "a stated absence needs no citation" in with_gap
    # ...and the row itself still SAYS it is empty, in the reader-safe FACT vocabulary (D-PQ EMPTY-1).
    assert "NO ROWS RETURNED" in with_gap
    no_gap = orc._numbers_block([full])
    assert "SCOPE NOTE" not in no_gap and "Do NOT cite the empty row" not in no_gap


def test_d2a_the_persona_says_the_value_slot_belongs_to_N_alone():
    """THE (2b) PROMPT HALF, extending the paragraph that already forbids a GROUPED token in a slot -- the
    grammar was written entirely in [N] vocabulary, so nothing had told the writer that the OTHER
    namespace cannot fill a slot at all. It must NOT contradict THE ONE EXEMPTION (a figure quoted from an
    evidence item may be typed in that item's own sentence), so the exit is named rather than closed."""
    hp = an._system(handles=True, episodes=True)
    assert "AN [E] HANDLE IS NEVER A FIGURE" in hp
    assert "THE ONE EXEMPTION" in hp                      # the legitimate exit is still open, and named
    assert hp.index("THE SLOT:") < hp.index("AN [E] HANDLE IS NEVER A FIGURE")
    for off in _persona_off_permutations():
        assert "AN [E] HANDLE IS NEVER A FIGURE" not in off


def test_m2a_the_menu_is_part_of_the_answer_and_it_is_claim_scoped():
    """G1 REMEDIATION-3 M2(a). THE MEASURED GAP: four explicit licences to omit a magnitude and ZERO
    affirmative instruction to use the menu. The design note above `_SYSTEM_HANDLES` records the omission
    as deliberate -- "NO DENSITY MANDATE ... caught by G1 clause (8)'s AGGREGATE band, checked after the
    fact, WITH NO INSTRUCTION TO THE WRITER" -- and clause (8) then failed on the covenant deck (11.74 and
    10.17 against an 11.84 floor). The MENU hypothesis is refuted: on `ab_mech_frost` the treatment arm's
    served rows are BYTE-IDENTICAL to control's (24 blocks / 158 values), control addressed 8 distinct
    rows, the treatment wrote zero handles, and every renderer counter on that row reads zero.

    THE FENCE IS THE POINT AND IT IS PINNED HERE, not just written: the sentence is CLAIM-SCOPED and
    carries NO count, NO quota and NO minimum. A mandatory-citation grammar converts non-citation failures
    into MIS-citation failures (B7), which is the other whole-gate failure (R11) -- so it must sit BESIDE
    "NO HANDLE, NO MAGNITUDE" narrowing it, never replacing it."""
    hp = an._system(handles=True, episodes=True)
    assert "THE MENU IS PART OF THE ANSWER" in hp
    assert "FOR A CLAIM YOU ARE ALREADY MAKING" in hp
    assert "This is not a minimum and not a quota" in hp
    assert "a claim you are not making needs no handle" in hp
    # the licence it NARROWS is still standing -- the pair is the contract, not the new half alone
    assert "NO HANDLE, NO MAGNITUDE -- and that is allowed" in hp
    assert "do not sprinkle handles to look grounded" in hp
    assert hp.index("NO HANDLE, NO MAGNITUDE") < hp.index("THE MENU IS PART OF THE ANSWER")
    # ...and NOTHING in it states a floor, a count or a share
    for quota in ("at least", "at minimum", "a minimum of", "%", "every row", "all of the rows"):
        assert quota not in hp[hp.index("THE MENU IS PART OF THE ANSWER"):
                               hp.index("STILL WRITE, EXACTLY AS BEFORE")], quota


def test_m2b_the_one_exemption_is_correct_not_a_loophole():
    """G1 REMEDIATION-3 M2(b). The artifacts show the writer reaching PAST the exemption rather than using
    it: `d2_inv4` / `ab_verif_palm_levy` minted a PSEUDO-HANDLE for a figure it was already licensed to
    type ("raised the export levy by [N-not-in-record text, but E24 states] \\"2.5 percent to 12.5
    percent\\""). The paragraph stated the exemption as a SURVIVAL rule -- "the only sentence in which a
    typed figure survives" -- which reads as a hole in the lint, so a careful writer invented a token
    instead. It must sit WITH that paragraph and must not re-open the general typing ban."""
    hp = an._system(handles=True, episodes=True)
    assert "AND USING THAT EXEMPTION IS CORRECT, NOT A LOOPHOLE" in hp
    assert "it is not a lint escape and nothing is deducted for it" in hp
    assert "Do NOT invent a substitute token to avoid typing it" in hp
    assert hp.index("THE ONE EXEMPTION") < hp.index("AND USING THAT EXEMPTION IS CORRECT")
    # the ban itself is untouched: every OTHER typed figure still costs the sentence
    assert "Every other typed figure is a lint violation" in hp
    assert "IN THE SAME SENTENCE AS THAT ITEM'S [E] HANDLE" in hp


def test_m2_the_off_arm_is_byte_identical_on_every_persona_permutation():
    """D-HP-16's "SHIPS CONDITIONALLY OR IT DOES NOT SHIP", measured rather than asserted, for BOTH M2
    halves. `_SYSTEM_HANDLES` is appended only under `handles=True`, so the control persona in every
    permutation of the four independent legs carries none of it -- and the control arm of a re-run must be
    a control arm, or clause (8)'s denominator is measuring the treatment."""
    import itertools
    probes = ("THE MENU IS PART OF THE ANSWER", "FOR A CLAIM YOU ARE ALREADY MAKING",
              "AND USING THAT EXEMPTION IS CORRECT", "Do NOT invent a substitute token")
    seen = 0
    for outlook, episodes, recency, prov in itertools.product([False, True], [None, False, True],
                                                              [False, True], [False, True]):
        off = an._system(outlook=outlook, episodes=episodes, recency=recency, provenance=prov)
        for probe in probes:
            assert probe not in off, (probe, outlook, episodes, recency, prov)
        seen += 1
    assert seen == 24                       # 2 x 3 x 2 x 2, the whole OFF-arm surface
    for off in _persona_off_permutations():
        for probe in probes:
            assert probe not in off
    # ...and the treatment arm carries both halves on every one of its own permutations
    for outlook, episodes, recency, prov in itertools.product([False, True], [None, False, True],
                                                              [False, True], [False, True]):
        on = an._system(handles=True, outlook=outlook, episodes=episodes, recency=recency,
                        provenance=prov)
        for probe in probes:
            assert probe in on, (probe, outlook, episodes, recency, prov)


def test_the_plan_budget_firming_is_the_same_sentence_at_both_sites_and_off_arm_silent():
    """A2(b)'s LAW: `_PLAN_PROPERTY_DESC` and `_SYSTEM_HANDLES` are read in the SAME turn, so a budget
    stated firmly in one and loosely in the other is not a budget. The r2 set exceeded ~800 on 22 of 24
    rows; no cap and no knob were added (both trade a truncated answer for a truncated plan), so the only
    lever is the wording -- and it must be IDENTICAL at both sites."""
    firm = "the number to plan TO, not a line to drift past"
    hp = an._system(handles=True, episodes=True)
    assert firm in hp and firm in an._PLAN_PROPERTY_DESC
    assert "1,500 tokens" in hp and "1,500 tokens" in an._PLAN_PROPERTY_DESC
    assert "800" in hp and "800 TOKENS" in an._PLAN_PROPERTY_DESC          # same number, both sites
    for off in _persona_off_permutations():
        assert firm not in off
    assert an._PLAN_PROPERTY_DESC not in an._answer_tool()["input_schema"]["properties"]  # not on OFF
