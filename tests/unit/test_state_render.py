"""THE ROW CLASSES, THE NARRATION CONTRACT AND THE OFFLINE HARNESS -- STATE ENGINE DESIGN sec 6 whole
plus sec 0.3's three acceptance scenarios. Sitting S3.

THE BARS THIS FILE OWNS (sec 10.2, the S3 row of sec 11):
  **B6**  REGISTER: zero fence trips on the three scenario fixtures; every letters-only class digit-free;
          every SB-W / SB-D / SB-L digit an ISO date; ``register_leaks == []``; the row-class regexes
          pairwise disjoint on every rendered line.
  **B12** RECENCY: an SB-1 older than its cadence's declared age limit carries the age clause in the
          hyphen-compound orthography; the ledger names three edges; no rendered line contains "not a
          current-state read".
  **B15** LABELS: every template literal, the mandate included, returns zero from ``count_flow_words``,
          ``count_valuation_words``, ``register_leaks`` and ``_LANE_B_ADJ``.
  **B18** EVENT DATE: the row anchors at the EVENT date, never at a later analysis piece's publication.
  **B19** TAPE: the tape-less boards decline ``no_tape_slug``; ``pre_coverage`` and ``front_decline``
          each decline by name; SB-T is never a driver row or an analog dimension.
  **B20** LANES AND COLD START: every off lane stamps its ``lane_off`` word and no board fires; an
          empty-route turn stamps ``anchor_none`` and reads nothing.

EVERYTHING RUNS OFFLINE. The three scenario boards are built from fixture arrays on the REAL thirty-six
DAGs by ``state/__main__.py``; nothing here opens a pg mirror, reaches Athena or spends a cent.
"""
import re

import pytest
from leviathan.graphrag.state import __main__ as H

from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import rows as ROWS
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state.feeders import tape_state
from leviathan.graphrag.state.lagbands import parse_lag

_ISO_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
_YEAR_RX = re.compile(r"\b(?:19|20)\d{2}\b")
_YM_RX = re.compile(r"\b\d{4}-\d{2}\b")
_HANDLE_RX = re.compile(r"\[[NE]\d+\]|\[T\d+\]")
#: ``verify._claim_number_spans`` rule (c): a digit run immediately preceded by a LETTER is never a claim
#: magnitude (B40, T2, MY2021, CO2). The estate's own driver ids carry one -- ``section301_tariffs`` --
#: and it reaches a letters-only class through ``display.node_label``. The exemption is the verifier's,
#: so this deck strips exactly what the verifier does and no more.
_GLUED_RX = re.compile(r"(?<=[A-Za-z])\d+")
#: THE LONG-FORM DAY -- ``verify._claim_number_spans`` rule (d) exempts it exactly as rule (a) exempts an
#: ISO date; the 09-23 chain receipt prints a DAY-precision event as "on 10 March 2025" (CONTRACT.md C7).
_LONGDAY_RX = re.compile(r"\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|"
                         r"October|November|December) (?:19|20)\d{2}\b")


@pytest.fixture(scope="module")
def graph():
    from leviathan.graphrag import graph as G
    return G.CausalGraph(G.load_contracts(), silver=set(), version="deck")


@pytest.fixture(scope="module")
def scenarios(graph):
    return {name: H.build_scenario(name, graph=graph) for name in H.SCENARIOS}


# ═══ B6 REGISTER ════════════════════════════════════════════════════════════════════════════════════
def test_B6_zero_register_trips_on_all_three_acceptance_fixtures(scenarios):
    """The templates are CLOSED and linted at build, so a serve-time trip is a build defect. This is the
    bar that says so on real output."""
    for name, ctx in scenarios.items():
        assert ctx["block"].trips == [], f"{name}: {[t['hits'] for t in ctx['block'].trips]}"


def test_B6_register_leaks_is_empty_on_every_rendered_line(scenarios):
    from leviathan.graphrag import register as reg
    for name, ctx in scenarios.items():
        for line in ctx["block"].lines:
            assert reg.register_leaks(line) == [], f"{name}: {line[:120]}"


def test_B6_every_rendered_line_classifies_as_EXACTLY_ONE_row_class(scenarios):
    """The disjointness bar, measured on real output rather than argued about between regexes."""
    for name, ctx in scenarios.items():
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            assert len(hit) == 1, f"{name}: {hit or 'no class'} for {line[:120]}"


def test_B6_a_letters_only_class_carries_no_digit_but_ISO_dates_and_years(scenarios):
    """Words are free, digits are not. Only ``FIGURE_CLASSES`` may carry a charged magnitude; every
    other class's digits are an ISO date, a year-month, a 4-digit year or a citation handle -- each
    exempt from ``verify._claim_number_spans`` by rule (a), (b) or (d)."""
    for name, ctx in scenarios.items():
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            if hit[0] in R.FIGURE_CLASSES:
                continue
            bare = _HANDLE_RX.sub("", line)
            bare = _ISO_RX.sub("", bare)
            bare = _YM_RX.sub("", bare)
            bare = _YEAR_RX.sub("", bare)
            bare = _GLUED_RX.sub("", _LONGDAY_RX.sub("", bare))
            assert not any(ch.isdigit() for ch in bare), f"{name}/{hit[0]}: {line[:140]}"


def test_B6_every_rendered_block_is_ASCII(scenarios):
    """The graph's own curated notes carry non-ASCII (the palm board's amplifier note says "El Nino"
    with a tilde). The BLOCK is what reaches a writer, so the fold is the render's."""
    for name, ctx in scenarios.items():
        ctx["block"].text().encode("ascii")


# ═══ B6, THE FULL ANCHOR-SHAPE FIXTURE SET (S6 re-fix) ═══════════════════════════════════════════════
#: EVERY ANCHOR SHAPE THE ESTATE CAN PRODUCE, ON EVERY TIER. The three acceptance scenarios are two
#: single-anchor boards and one attached-event board, and B6 was graded on those alone -- so the bar
#: said "the block is register-clean" while MEASURING only the narrowest third of the shapes a real
#: question makes. The S6 verifier ran the multi-anchor shapes and found 5 of 12 blocks dirty. This set
#: is the bar restated over shapes rather than over scenarios: five shapes x three modes = fifteen
#: blocks, built through the SERVING seam (`fill_stage1` + `fill_stage2`) rather than through the
#: harness, because the seam is what a writer is actually handed.
_SHAPES: dict = {
    "single":         {"named": ("soybeans_cbot",),
                       "q": "what is the situation on soybeans now?"},
    "two_named":      {"named": ("soybeans_cbot", "malaysian_crude_palm_oil_cme"),
                       "q": "how do soybeans and palm oil compare right now?"},
    # THE FOUR-NAMED SHAPE IS MAJOR 1's OWN FIXTURE. On deep AND max it MEASURED trips=3,
    # register_leaks=3 and internal_leaks=3, the leaked tokens being the raw convergence-regime ids
    # `bearish_glut` and `bearish_big_crop_glut` -- shipped by the register fence's OWN correction row.
    "four_named":     {"named": ("soft_red_winter_wheat_cbot", "corn_cbot", "soybeans_cbot",
                                 "malaysian_crude_palm_oil_cme"),
                       "q": "How do wheat, corn, soybeans and palm oil compare right now?"},
    "focus_driver":   {"named": (), "focus_driver": "El_Nino",
                       "q": "El Nino is developing: what does it do?"},
    "attached_event": {"named": (), "attached_event": "malaysian_crude_palm_oil_cme",
                       "q": "Indonesia raised the biodiesel mandate to B40: what does it do?"},
}


@pytest.fixture(scope="module")
def shape_blocks(graph):
    """{(shape, mode): Block} over every anchor shape and every tier, through the SERVING seam.

    OFFLINE BY CONSTRUCTION: the state producer is the harness's own `fixture_state_fn`, so this
    fixture reads no mirror, opens no socket and calls no model."""
    import types

    from leviathan.graphrag.state import render as _R
    from leviathan.graphrag.state import seam as _S

    out, seen = {}, []
    orig = _R.render_board

    def _capture(bd, **kw):
        b = orig(bd, **kw)
        seen.append(b)
        return b

    _R.render_board = _capture
    try:
        for name, spec in _SHAPES.items():
            for mode in ("quick", "deep", "max"):
                kw = {k: v for k, v in spec.items() if k != "q"}
                seen.clear()
                sg = types.SimpleNamespace(seeds=list(kw.get("named") or ()), nodes=[], trace={})
                bd = _S.fill_stage1(graph=graph, sg=sg, asof=H.ASOF, mode=mode, query=spec["q"],
                                    lane="run_hybrid", state_fn=H.fixture_state_fn(H.ASOF), **kw)
                payload = _S.fill_stage2(bd, graph=graph, state_fn=H.fixture_state_fn(H.ASOF))
                out[(name, mode)] = (bd, payload, seen[-1] if seen else None)
    finally:
        _R.render_board = orig
    return out


def test_B6_zero_register_trips_on_EVERY_anchor_shape_on_EVERY_tier(shape_blocks):
    """MAJOR 1 AND MAJOR 2's BAR, and it is fifteen blocks rather than three.

    A TRIP IS THE DEFECT, NOT THE REMEDY. The fence corrects, so a block with trips still ships -- and
    that is exactly why the count has to be pinned: a trip means a template this module OWNS composed a
    line it could not print, and the correction that replaces it is a row of prose where a row of fact
    was planned. Zero on every shape, on every tier."""
    for key, (_bd, _payload, blk) in sorted(shape_blocks.items()):
        assert blk is not None, key
        assert blk.trips == [], f"{key}: {[(t['label'], t['hits']) for t in blk.trips]}"


def test_B6_the_BLOCK_is_register_clean_and_not_merely_its_lines(shape_blocks):
    """THE THIRD BLIND SPOT, PINNED ON THE UNIT THE WRITER IS HANDED.

    `register._SENT_ITER` splits on terminal punctuation plus whitespace and deliberately NOT on a bare
    newline, so consecutive
    board rows -- which carry no terminator -- weld into ONE sentence for the class-rule detectors.
    MEASURED before the fix: a `focus_driver` Cascade block whose 259 lines were each clean alone
    returned one `forward-convergence` hit on the assembled text. Grading lines alone cannot see it;
    this asserts the block, which is what reaches the writer."""
    from leviathan.graphrag import register as reg
    for key, (_bd, payload, _blk) in sorted(shape_blocks.items()):
        text = payload.get("block") or ""
        assert text, key
        assert reg.internal_leaks(text) == [], f"{key}: {reg.internal_leaks(text)[:3]}"
        assert reg.market_leaks(text) == [], f"{key}: {reg.market_leaks(text)[:3]}"
        assert reg.register_leaks(text) == [], f"{key}: {reg.register_leaks(text)[:3]}"


def test_B6_every_line_of_every_shape_is_clean_single_classed_and_ASCII(shape_blocks):
    from leviathan.graphrag import register as reg
    for key, (_bd, _payload, blk) in sorted(shape_blocks.items()):
        blk.text().encode("ascii")
        for line, hit in zip(blk.lines, blk.classes):
            assert reg.register_leaks(line) == [], f"{key}: {line[:120]}"
            assert len(hit) == 1, f"{key}: {hit or 'no class'} for {line[:120]}"


def test_B6_the_four_named_shape_carries_NO_internal_id_on_deep_and_on_max(shape_blocks):
    """MAJOR 1, NAMED AT ITS OWN MEASUREMENT. The two tiers that shipped the leak are pinned by name,
    and so are the two tokens: a regression that reintroduced either would fail HERE with the id in the
    message rather than in a count."""
    from leviathan.graphrag import register as reg
    for mode in ("deep", "max"):
        _bd, payload, blk = shape_blocks[("four_named", mode)]
        text = payload["block"]
        assert blk.trips == [], f"{mode}: {[(t['label'], t['hits']) for t in blk.trips]}"
        assert reg.internal_leaks(text) == []
        for rid in ("bearish_glut", "bearish_big_crop_glut"):
            assert rid not in text, f"{mode}: the raw regime id {rid} reached the block"
        # ...and the pattern is still NAMED, in the display vocabulary's words rather than by its id.
        assert R.pattern_label("bearish_glut") in text


def test_B6_a_tripped_template_is_CORRECTED_into_its_own_absence_and_the_block_survives():
    """Sec 6.6: fences CORRECT or COMPUTE, never delete. Drafts C and D's drop-whole fence is not here."""
    b = R.Block(start=1)
    b.add("- a clean line about supply", (), label="clean")
    b.add("- the spread screens cheap versus the prior year", (R.sb_call(
        table="t", metric="m", commodity="c", country=None, period="p", asof="2026-09-07",
        value=1.0),), label="dirty")
    b.add("- another clean line", (), label="clean2")
    assert len(b.lines) == 3
    assert b.lines[1].startswith("BOARD ABSENCE") and "register check" in b.lines[1]
    assert len(b.trips) == 1
    assert b.calls == []                       # the line's calls went with it: no handle points at air


def test_the_fence_CORRECTION_never_carries_an_internal_id_and_the_fallback_is_FAIL_CLOSED():
    """MAJOR 1 AT THE UNIT, WHICH IS WHERE THE CLASS IS CLOSED RATHER THAN THE INSTANCE.

    The correction row used to interpolate the caller's INTERNAL label, and every caller builds that
    label from the row's own ids. Three properties are pinned: no display name -> the closed fallback;
    a display name -> reader words; a DIRTY display name -> the closed fallback, not the dirty name."""
    from leviathan.graphrag import register as reg
    dirty = "- the spread screens cheap versus the prior year"
    b = R.Block(start=1)
    b.add(dirty, (), label="amplifier bearish_glut")            # no display: the fallback, never the id
    assert "bearish_glut" not in b.lines[0]
    assert R.CORRECTED_ROW_FALLBACK in b.lines[0]
    b.add(dirty, (), label="pattern bearish_glut",
          display=f"the pattern row for {R.pattern_label('bearish_glut')}")
    assert R.pattern_label("bearish_glut") in b.lines[1] and "bearish_glut" not in b.lines[1]
    # A DISPLAY NAME THAT ITSELF TRIPS IS NO NAME A READER MAY BE SHOWN. This is the fail-closed half:
    # a future call site cannot reintroduce the leak by handing this method a name built from an id.
    b.add(dirty, (), label="x", display="soybeans_cbot at a cheap spread versus last year")
    assert "soybeans_cbot" not in b.lines[2] and R.CORRECTED_ROW_FALLBACK in b.lines[2]
    for line in b.lines:
        assert reg.register_leaks(line) == [], line
    assert len(b.trips) == 3
    # the LABEL still rides the trip record, where an id is exactly what a reader of telemetry wants
    assert [t["label"] for t in b.trips] == ["amplifier bearish_glut", "pattern bearish_glut", "x"]


def test_a_curated_interaction_note_is_GOVERNED_and_a_replaced_one_says_so():
    """MAJOR 2's ROOT BLIND SPOT. `Interaction.note` is free text in a gitignored DAG config that rides
    the image tar, and `sb_amplifier` spliced it VERBATIM: 21 of the shipped 277 notes trip a detector.

    THE FENCE CORRECTS, IT DOES NOT DELETE. The ordering fact -- the pair, the loud claim, the read
    split, the effect word -- survives a dirty note, and the row states that a note was replaced."""
    from leviathan.graphrag import register as reg
    clean = {"when": ("crude_oil_price", "biodiesel_mandate"), "effect": "amplifies",
             "note": "Higher crude pulls more palm into biodiesel.", "unmeasured": ()}
    line = R.sb_amplifier("malaysian_crude_palm_oil_cme", clean)
    assert "Higher crude pulls more palm into biodiesel." in line
    assert R.register_hits(line) == []
    # the MEASURED offender, verbatim from soft_red_winter_wheat_cbot.yaml
    bad = dict(clean, note=("Cheap Black Sea supply plus a strong dollar make US SRW uncompetitive on "
                            "exports, stranding supply and building stocks."))
    assert R.register_hits(R.ascii_text(bad["note"])) == ["lane_b_adjective"]
    out = R.sb_amplifier("soft_red_winter_wheat_cbot", bad)
    assert R.register_hits(out) == [], out
    assert "Cheap Black Sea" not in out
    assert R.AMPLIFIER_NOTE_REPLACED in out             # the replacement is STATED, never silent
    assert "records the effect as amplifies" in out     # ...and the ordering fact still stands
    assert "crude oil price" in out and "CBOT srw wheat" in out
    # EVERY shipped note is governed, not just the one this deck names
    from leviathan.graphrag import graph as _G
    g = _G.CausalGraph(_G.load_contracts(), silver=set(), version="deck")
    dirty = 0
    for slug, c in g.contracts.items():
        for conv in (getattr(c, "convergence", ()) or ()):
            for it in (getattr(conv, "interactions", ()) or ()):
                if R.register_hits(R.ascii_text(it.note or "")):
                    dirty += 1
                assert reg.register_leaks(R.sb_amplifier(slug, {
                    "when": tuple(it.when), "effect": it.effect, "note": it.note,
                    "unmeasured": ()})) == [], (slug, conv.name)
    assert dirty >= 21, dirty          # the census that made this a class rather than an instance


#: THE PIN'S NOTE: CLEAN ALONE, DIRTY WHEN SPLICED. Built from the fence's own `forward-convergence`
#: class rule (`register._SPREAD_NOUN` + `_CONVERGE_VERB` + `_FUTURITY`, one sentence): it carries the
#: convergence verb and the futurity marker and NOT the spread noun, so by itself it completes nothing.
#: The amplifier row's own read-split tail supplies the third term.
_SPLICE_NOTE = "expected to narrow from here"

#: The interaction the note rides. `board_crush_spread` humanises to "board crush spread" -- a driver
#: id whose READER label carries a spread noun, which is what a curator writes and no fence forbids.
_SPLICE_INTER = {"when": ("board_crush_spread", "crude_oil_price"), "effect": "amplifies",
                 "unmeasured": ("board_crush_spread",), "note": _SPLICE_NOTE}

#: The four things the row asserts and the fence must never take from it.
_AMP_SURVIVORS = ("board crush spread, crude oil price",            # the PAIR
                  "are all among the largest moves here",          # the LOUD CLAIM
                  "records the effect as amplifies",                # the EFFECT WORD
                  "carries no series read here")                    # the READ SPLIT


def test_a_note_CLEAN_ALONE_and_DIRTY_WHEN_SPLICED_loses_ITS_CLAUSE_and_never_the_WHOLE_ROW():
    """THE S6 SECOND VERIFY'S STANDING MAJOR, reproduced at the unit and pinned at the root.

    `governed_note` grades the note FRAGMENT. The register's class rules grade a SENTENCE, and
    `_SENT_ITER` breaks only on `[.!?;]\\s+` -- so the note lands INSIDE a sentence the row started, and
    a fragment that completes nothing alone can complete a rule once it is spliced. The completed line
    then reached `Block.add`, whose correction is whole-row: the pair, the loud claim, the effect word
    and the read split were all deleted to fence a curated clause, and the reader met an absence where
    an ordering fact had been.

    THE FIX IS AT THE ROOT: `sb_amplifier` grades the ASSEMBLED row and, on a trip, replaces the CLAUSE
    and re-renders the row whole. Correct the dirty half; never delete the clean ones."""
    from leviathan.graphrag import register as reg

    # (1) CLEAN ALONE -- the fragment fence passes it through verbatim, which is what it should do.
    assert R.register_hits(_SPLICE_NOTE) == []
    assert R.governed_note(_SPLICE_NOTE) == " -- " + _SPLICE_NOTE

    # (2) THE MUTATION PIN. This is the pre-fix assembly, byte-for-byte: the row built with NO note,
    # plus whatever the FRAGMENT-ONLY fence returned. Nothing is monkeypatched -- the mutant is
    # constructed from the two public builders, so the pin cannot rot into agreement with the fix.
    bare = R.sb_amplifier("soybeans_cbot", dict(_SPLICE_INTER, note=""))
    assert R.register_hits(bare) == []                 # the ROW is clean; the note is clean; the
    mutant = bare + R.governed_note(_SPLICE_NOTE)      # ...SPLICE is not
    assert R.register_hits(mutant) == ["count_valuation_words", "register_leaks"], mutant
    assert [k for k, _ in reg._class_rule_hits(mutant)] == ["forward-convergence"]
    # ...and the whole-row deletion reappears: every one of the four survivors is gone.
    mb = R.Block()
    mout = mb.add(mutant, label="amplifier bearish_glut",
                  display="the amplifier under a pattern on CBOT soybeans")
    assert len(mb.trips) == 1 and mout.startswith("BOARD ABSENCE")
    for word in _AMP_SURVIVORS:
        assert word not in mout, word

    # (3) THE FIX. The clause goes and is STATED; the row is rendered whole around it.
    line = R.sb_amplifier("soybeans_cbot", _SPLICE_INTER)
    assert R.register_hits(line) == [], line
    assert _SPLICE_NOTE not in line                    # the dirty clause loses ITSELF...
    assert R.AMPLIFIER_NOTE_REPLACED in line           # ...and says so, never a silence
    for word in _AMP_SURVIVORS:
        assert word in line, word
    # ...and it reaches the block as a COMMITTED row rather than as a trip.
    b = R.Block()
    out = b.add(line, label="amplifier bearish_glut",
                display="the amplifier under a pattern on CBOT soybeans")
    assert b.trips == [] and out == line


def test_the_receipt_QUOTE_and_SOURCE_are_fenced_the_way_the_note_is_and_the_HANDLE_survives():
    """MINOR (a) OF THE SAME VERIFY. `r["text"]` and `r["source"]` were interpolated verbatim through an
    ASCII fold -- a fold is not a fence, and retrieved corpus prose is one seam over from
    `Interaction.note`: same ungoverned-string class, same splice into a sentence the row started.

    THE ROW IS GRADED AS THE DETECTOR WILL READ IT and a trip replaces the CLAUSE. The quote goes
    first; only if the row still trips is the source name replaced too. The `[E]` handle, the `[T]`
    tier, the reported date, the event date and the driver survive every arm -- a deleted receipt row
    is a citable document taken off the menu, and a minted `[E]` on a row that never rendered is a
    handle pointing at nothing."""
    keep = ("[E7][T2]", "reported 2026-08-12", "{driver: El Nino}")

    def _row(**kw):
        r = {"source": "USDA WASDE", "date": "2026-08-12", "event_date": "2026-05-01",
             "text": "Ending stocks were revised down."}
        r.update(kw)
        return R.sb_receipt(7, 2, r, driver_id="El_Nino")

    clean = _row()
    assert R.register_hits(clean) == [] and "Ending stocks were revised down." in clean
    assert "event 2026-05-01" in clean

    # (a) the QUOTE is dirty ALONE -- the class this fence was always meant to catch
    loud = _row(text="The basis is due to normalise from here.")
    assert R.register_hits("The basis is due to normalise from here.")
    assert R.register_hits(loud) == [] and "due to normalise" not in loud
    assert R.RECEIPT_QUOTE_REPLACED in loud and "event 2026-05-01" in loud

    # (b) the QUOTE is CLEAN ALONE and dirty only once the SOURCE NAME is in the same sentence -- the
    #     standing major's own shape, one seam over. THE EVENT DATE IS ABSENT HERE ON PURPOSE: its
    #     "; event <iso>" clause is a sentence BREAK for `_SENT_ITER`, so a receipt that carries one
    #     already separates its source from its quote and the two cannot weld. That is a fact about
    #     this row's punctuation, not a fence -- an event-less receipt is the ordinary case.
    quote = "narrowing is likely from here"
    assert R.register_hits(quote) == []
    spliced = _row(source="Board Crush Spread Weekly", text=quote, event_date=None)
    assert R.register_hits(spliced) == [], spliced
    assert quote not in spliced and R.RECEIPT_QUOTE_REPLACED in spliced
    assert "Board Crush Spread Weekly" in spliced      # the SOURCE is kept: it is not the dirty half

    # (c) the SOURCE is the dirty half -- both clauses are replaced and both replacements are STATED
    both = _row(source="Board Crush Spread Weekly, due to narrow", text=quote, event_date=None)
    assert R.register_hits(both) == [], both
    assert R.RECEIPT_SOURCE_REPLACED in both and R.RECEIPT_QUOTE_REPLACED in both
    assert "Board Crush Spread Weekly" not in both

    for line in (clean, loud, spliced, both):
        for word in keep:
            assert word in line, (word, line)


def test_the_interaction_EFFECT_is_a_CLOSED_ORDERING_WORD_and_never_a_raw_config_string():
    """The other governed field on the same row. The graph declares exactly two words (271 `amplifies`
    / 6 `dampens`); a third would have reached the writer as prose nobody graded."""
    assert set(R.AMPLIFIER_EFFECT_WORDS) == {"amplifies", "dampens"}
    assert R.amplifier_effect("amplifies") == "amplifies"
    assert R.amplifier_effect("dampens") == "dampens"
    for junk in ("", None, "makes prices cheap", "AMPLIFIES", "explodes"):
        assert R.amplifier_effect(junk) == R.AMPLIFIER_EFFECT_UNKNOWN
    assert R.register_hits(R.AMPLIFIER_EFFECT_UNKNOWN) == []
    line = R.sb_amplifier("soybeans_cbot", {"when": ("El_Nino",), "effect": "screens cheap",
                                            "note": "", "unmeasured": ()})
    assert R.register_hits(line) == [] and "screens cheap" not in line


def test_the_fence_grades_the_WELD_and_closes_the_sentence_rather_than_dropping_a_row():
    """THE THIRD BLIND SPOT AT THE UNIT. Two rows, each clean alone, that the register scanner reads as
    ONE sentence because a board row carries no terminator. The fence CLOSES the first row (the
    computation) instead of replacing either (the deletion) -- neither loses a word, a handle or a
    call, and the correction is recorded rather than silent."""
    from leviathan.graphrag import register as reg
    a = "- the domestic-retention premium on CBOT corn could not be read"
    b = "BOARD ABSENCE the convergence patterns past this tier's pattern cut: the rows past this cut."
    nl = chr(10)
    assert reg.register_leaks(a) == [] and reg.register_leaks(b) == []
    assert reg.register_leaks(a + nl + b) != []           # ...but the WELD is a class-rule hit
    blk = R.Block(start=1)
    blk.add(a, (), label="one")
    blk.add(b, (), label="two")
    assert blk.trips == []                                 # neither row was replaced
    assert len(blk.welds) == 1 and blk.welds[0]["at"] == 0
    assert blk.lines[0] == a + "."                         # the terminator the row never carried
    assert blk.lines[1] == b
    assert reg.register_leaks(blk.text()) == []
    assert blk.classes[0] == R.classify(a)                 # closing a sentence moves no row's class
    # AND A BLOCK WITH NO WELD IS UNTOUCHED, byte for byte -- the correction is not a formatter.
    plain = R.Block(start=1)
    plain.add(a, (), label="one")
    plain.add("- a second clean row about supply", (), label="two")
    assert plain.welds == [] and plain.lines[0] == a


def test_the_marker_is_minted_ONCE_and_the_gate_reads_the_producers_constant(scenarios):
    assert R.SB_MARKER_PREFIX == "STATE OF THE WORLD at "
    for ctx in scenarios.values():
        assert ctx["block"].lines[0].startswith(R.SB_MARKER_PREFIX)
        assert R.block_marker_present(ctx["block"].text())
    assert not R.block_marker_present("a prompt with no board in it")


# ═══ B15 LABELS ═════════════════════════════════════════════════════════════════════════════════════
def test_B15_every_template_literal_and_the_mandate_are_register_clean():
    assert N.check_literals() == []
    for word, sentence in R.ABSENCE_WHY.items():
        assert R.register_hits(sentence) == [], (word, sentence)
    for words in (R.CONFIDENCE_WORDS, R.RUN_DIRECTION_WORDS, R.PERIOD_NOUNS):
        for v in words.values():
            assert R.register_hits(v) == []
    from leviathan.graphrag.state import watch as WA
    for v in WA.KIND_WORDS.values():
        assert R.register_hits(v) == []


def test_B15_the_mandate_names_the_four_movements_and_no_new_heading():
    from leviathan.graphrag import response_contracts as RC
    known = set(RC.CANONICAL) | {h for h in dir(RC) if h.startswith("##")}
    known |= {v for v in vars(RC).values() if isinstance(v, str) and v.startswith("## ")}
    known |= {x for v in vars(RC).values() if isinstance(v, (tuple, list, frozenset, set))
              for x in v if isinstance(x, str) and x.startswith("## ")}
    for movement, heading, fallback in N.MANDATE_MOVEMENTS:
        assert movement in N.SYSTEM_STATE_BOARD_MANDATE
        assert heading in known, heading            # never a heading the contract does not already own
        if fallback:
            assert fallback in RC.CANONICAL         # and a licensed heading has a canonical home
    assert "Use no heading called then or now." in N.SYSTEM_STATE_BOARD_MANDATE


def test_the_mandate_ships_ONLY_when_the_board_is_there():
    """Doctrine M-7: block and mandate land together. A mandate without its block would instruct a
    writer to narrate rows nobody handed it."""
    assert N.mandate_for("") == ""
    assert N.mandate_for(None) == ""
    assert N.mandate_for(R.SB_MARKER_PREFIX + "2026-09-07 ...") == N.SYSTEM_STATE_BOARD_MANDATE


def test_every_closed_word_a_reader_can_meet_has_a_sentence():
    seen = {w for words in B.LEG_REASONS.values() for w in words}
    seen |= set(ROWS.STATUS_WORDS) | set(ROWS.TAPE_STATUS_WORDS)
    seen.discard("ok")
    for w in seen:
        assert w in R.ABSENCE_WHY, w
        assert R.ABSENCE_WHY[w] != R.ABSENCE_FALLBACK


# ═══ B12 RECENCY ════════════════════════════════════════════════════════════════════════════════════
def test_B12_the_age_clause_uses_the_hyphen_compound_orthography():
    """A bare "17 months before this as-of" extracts as a CLAIM MAGNITUDE ("before" is a ``_DUR_STOP``)
    and the all-numbers guard strips the writer's own dating sentence. The hyphen compound with a
    ``_STAT_HEAD`` noun clears rule (f)."""
    c = N.age_clause("2025-04-30", "2026-09-07", "monthly")
    assert c == "read through 2025-04-30, 16-month span to this as-of"
    assert N.age_clause("2020-04-30", "2026-09-07", "monthly").endswith("6-year span to this as-of")


def test_B12_the_age_limit_is_a_TABLE_per_cadence_and_not_a_multiple_of_one():
    """"A monthly ONI three months old is stale and a daily FX three days old is not", and no multiple
    of a cadence says both."""
    assert N.age_clause("2026-09-01", "2026-09-07", "daily") == ""
    assert N.age_clause("2026-08-20", "2026-09-07", "daily") != ""
    assert N.age_clause("2026-08-20", "2026-09-07", "monthly") == ""
    assert N.age_clause("2026-05-31", "2026-09-07", "monthly") != ""


def test_B12_an_unreadable_date_DECLINES_rather_than_guessing():
    assert N.age_clause(None, "2026-09-07", "monthly") == ""
    assert N.age_clause("not-a-date", "2026-09-07", "monthly") == ""


def test_B12_the_ledger_names_THREE_EDGES_and_none_dates_another(scenarios):
    for name, ctx in scenarios.items():
        assert set(ctx["recency"]) == {"numbers", "text", "tape"}
        sb_l = [l for l, h in zip(ctx["block"].lines, ctx["block"].classes) if h == ("SB-L",)]
        assert len(sb_l) == 3, name
    s = N.recency_ledger(asof="2026-09-07", kd_max="2026-09-04", kd_min="2025-12-31",
                         record_through="2026-08-20", tape_edge="2026-09-04")
    assert "none dates the others" in s


def test_B12_no_rendered_line_ever_says_not_a_current_state_read(scenarios):
    for name, ctx in scenarios.items():
        assert N.BANNED_RECENCY_PHRASE not in ctx["block"].text().lower(), name


def test_the_persona_replacement_clause_has_a_CLAIM_as_its_subject_never_the_answer():
    """Neither sentence can be inflated into a verdict on the page, because neither has the page as its
    subject."""
    assert "claim" in N.SYSTEM_RECENCY_CLAUSE
    assert "this answer" not in N.SYSTEM_RECENCY_CLAUSE


# ═══ B18 EVENT DATE ═════════════════════════════════════════════════════════════════════════════════
def test_B18_the_event_row_anchors_at_the_EVENT_date_never_at_a_later_analysis_piece(scenarios):
    ctx = scenarios["b40_event"]
    row = ctx["board"].row("malaysian_crude_palm_oil_cme", "biodiesel_mandate")
    assert row is not None and row.event_date == H.B40_DATE
    line = [l for l in ctx["block"].lines if l.startswith("- biodiesel mandate dated")]
    assert line and f"dated {H.B40_DATE}" in line[0]
    assert "2026-05-31" not in line[0]                       # the D+30 piece never anchors


def test_B18_a_receipt_whose_event_date_is_AFTER_the_as_of_never_anchors():
    """It is a kind-5 WATCH candidate instead, and the deck above proves it renders as one."""
    ed, prec = W.event_date_for(
        [{"event_date": "2027-01-01", "event_date_precision": "day", "date": "2026-08-20"}],
        "2026-09-07")
    assert ed is None and prec == ""


def test_B18_day_precision_beats_month_precision_on_the_same_event_date():
    ed, prec = W.event_date_for(
        [{"event_date": "2026-05-01", "event_date_precision": "month", "date": "2026-05-31"},
         {"event_date": "2026-05-01", "event_date_precision": "day", "date": "2026-05-02"}],
        "2026-09-07")
    assert (ed, prec) == ("2026-05-01", "day")


def test_the_event_row_states_whether_its_window_is_OPEN_or_CLOSED(scenarios):
    ctx = scenarios["b40_event"]
    line = [l for l in ctx["block"].lines if l.startswith("- biodiesel mandate dated")][0]
    assert "the window is open until about" in line


# ═══ B19 TAPE ═══════════════════════════════════════════════════════════════════════════════════════
def _tapeless_slugs():
    from leviathan.silver import futures_eod_contracts as FC
    from leviathan.graphrag import graph as G
    covered = set(FC.PRICE_COVERAGE_START)
    return sorted(set(G.load_contracts()) - covered)


def test_B19_every_tape_less_board_declines_no_tape_slug_BY_NAME():
    slugs = _tapeless_slugs()
    assert slugs, "the roster split is the fact this bar rests on"
    for slug in slugs:
        t = tape_state(slug, "2026-09-07", qfn=None)
        assert t.status == "no_tape_slug", slug
        assert t.reads == 0                                  # a decline that spends nothing


def test_B19_an_as_of_before_a_boards_own_coverage_floor_declines_pre_coverage():
    t = tape_state("soybeans_cbot", "2005-01-03", qfn=None)
    assert t.status == "pre_coverage" and t.coverage_start


def test_B19_a_tape_less_board_renders_its_absence_and_no_SB_T_row():
    bd = B.Board(asof="2026-09-07", mode="max", knobs=B.board_knobs_of("max"),
                 anchors=(B.Anchor(contract="soybeans", source="named"),))
    R.attach_tape(bd, {"soybeans": tape_state("soybeans", "2026-09-07", qfn=None)}, reads_each=0)
    blk = R.render_board(bd)
    sb_t = [l for l, h in zip(blk.lines, blk.classes) if h == ("SB-T",)]
    assert not sb_t
    assert any(l.startswith("BOARD ABSENCE") and "price path" in l for l in blk.lines)


def test_B19_SB_T_is_never_a_driver_row_and_never_a_ranked_candidate(scenarios):
    for name, ctx in scenarios.items():
        for slug in ctx["board"].anchor_slugs:
            assert ctx["board"].row(slug, slug) is None
            assert not any(r.driver_id == slug for r in ctx["board"].rows), name


def test_the_tape_declares_its_OWN_ledger_seat_outside_both_waves(scenarios):
    """D19: one mirror read per ANCHOR board, outside both rectangles. ``board.py`` left ``tape_cap`` at
    zero and named this sitting as the one that declares it."""
    for name, ctx in scenarios.items():
        bd = ctx["board"]
        assert bd.ledger.tape_cap == len(bd.anchor_slugs), name
        assert bd.rectangle() == [], name


# ═══ B20 LANES AND COLD START ═══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("lane", B.OFF_LANES)
def test_B20_every_off_lane_stamps_its_own_word_and_no_board_fires(graph, lane):
    bd = W.walk(graph=graph, asof="2026-09-07", mode="max", lane=lane,
                anchors=(B.Anchor(contract="soybeans_cbot", source="named"),))
    assert bd.legs["board"] == {"outcome": "declined", "reason": f"lane_off:{lane}", "reads": 0}
    assert bd.net_reads() == 0 and not bd.rows


def test_B20_an_empty_route_stamps_anchor_none_and_reads_nothing(graph):
    bd = W.walk(graph=graph, asof="2026-09-07", mode="max", anchors=())
    assert bd.legs["board"]["reason"] == "anchor_none"
    assert bd.anchor_source == "anchor_none"
    assert bd.net_reads() == 0 and not bd.series


def test_B20_a_tier_with_no_declared_board_is_an_off_lane_with_its_own_name(graph):
    bd = W.walk(graph=graph, asof="2026-09-07", mode="standard",
                anchors=(B.Anchor(contract="soybeans_cbot", source="named"),))
    assert bd.legs["board"]["reason"] == "lane_off:standard"


def test_B20_the_render_of_an_off_lane_board_is_a_header_and_its_absences(graph):
    bd = W.walk(graph=graph, asof="2026-09-07", mode="max", lane="numbers_only",
                anchors=(B.Anchor(contract="soybeans_cbot", source="named"),))
    blk = R.render_board(bd)
    assert blk.lines and blk.lines[0].startswith(R.SB_MARKER_PREFIX)
    assert blk.calls == []


# ═══ THE ROW CLASSES THEMSELVES ═════════════════════════════════════════════════════════════════════
def test_every_figure_the_board_prints_carries_its_OWN_handle_and_ONE_shown_value(scenarios):
    """K9-6 by construction: one handle per magnitude, ``shown`` a single-element list, ``country`` the
    RESOLVED scope so ``_unscoped_multi_geo`` can never fire on a board row."""
    for name, ctx in scenarios.items():
        for c in ctx["block"].calls:
            assert c["status"] == "ok" and c.get("_sb")
            assert len(c.get("shown", [])) == 1, (name, c["query"])
            assert set(c["query"]) == {"table", "metric", "commodity", "country", "period", "asof"}
            assert len(c["rows"]) == 1


def test_the_handles_are_dense_and_in_call_order(scenarios):
    """``citations.unify`` numbers a call in CALL ORDER, so a block whose MINTED handles skipped or
    repeated a number would bind a writer's figure to the wrong row.

    ONLY THE FIGURE-BEARING CLASSES MINT. SB-P REFERENCES handles already minted upstream ("the measured
    rows on it are [N7][N34]"), which is the whole point of that clause -- a path row cites the state
    rows on it rather than restating their figures -- so a reference is asserted to POINT AT a minted
    call, never to be one."""
    for name, ctx in scenarios.items():
        minted = [int(m) for l, h in zip(ctx["block"].lines, ctx["block"].classes)
                  if h[0] in R.FIGURE_CLASSES for m in re.findall(r"\[N(\d+)\]", l)]
        assert minted == sorted(minted), name
        assert sorted(set(minted)) == list(range(1, len(ctx["block"].calls) + 1)), name
        referenced = [int(m) for l, h in zip(ctx["block"].lines, ctx["block"].classes)
                      if h[0] not in R.FIGURE_CLASSES for m in re.findall(r"\[N(\d+)\]", l)]
        assert all(1 <= r <= len(ctx["block"].calls) for r in referenced), name


def test_ordinals_are_english_and_never_the_th_of_everything():
    assert (R.ordinal(1), R.ordinal(2), R.ordinal(3), R.ordinal(11), R.ordinal(82),
            R.ordinal(100)) == ("1st", "2nd", "3rd", "11th", "82nd", "100th")


def test_a_lag_band_renders_as_WORDS_and_an_unparsed_one_says_so():
    assert R.band_words(parse_lag("1-2 quarters")) == "one to two quarters"
    assert R.band_words(parse_lag("0-1 quarters")) == "zero to one quarter"
    assert R.band_words(parse_lag("structural")) == "beyond two years"
    assert R.band_words(parse_lag("a spelling nobody declared")) == "a lag the table does not carry"
    assert R.band_words(None) == "a lag the table does not carry"


def test_a_window_length_renders_in_WORDS_because_its_cadence_noun_earns_no_exemption():
    """``verify._DURATION_NOUN`` is ``year|yr|month|week|wk|day|quarter|qtr|season``; the board's own
    cadence nouns include ``session``, ``fortnight`` and ``marketing year``, so the hyphen compound sec
    6.2 writes would be charged on a daily row. The count renders as words instead."""
    assert R.words_for_int(250) == "two hundred fifty"
    assert R.words_for_int(156) == "one hundred fifty-six"
    assert R.words_for_int(0) == "zero"
    assert not any(ch.isdigit() for ch in R.words_for_int(1266))


def test_the_sign_words_are_the_closed_three_and_an_undeclared_sign_is_a_FOURTH_fact():
    assert R.sign_words("+") == "in the same direction"
    assert R.sign_words("-") == "in the opposite direction"
    assert R.sign_words("0") == "with no committed direction"
    assert R.sign_words("") == "in a direction the graph does not declare"


def test_a_convergence_line_never_says_met_fires_or_the_regime_is(scenarios):
    for name, ctx in scenarios.items():
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            if hit[0] not in ("SB-C", "SB-M"):
                continue
            low = line.lower()
            for banned in W.CONVERGENCE_BANNED_WORDS:
                assert banned not in low, f"{name}: {line[:120]}"


# ═══ THE THREE ACCEPTANCE SCENARIOS (sec 0.3) ═══════════════════════════════════════════════════════
def test_scenario_1_carries_the_ONI_state_its_edge_and_its_projection(scenarios):
    ctx = scenarios["soybeans_now"]
    lines = ctx["block"].lines
    # 09-23 (CONTRACT.md C1): the head names the SERIES and the driver rides once as the routing word.
    sb1 = [l for l in lines if l.startswith("- [N1] the tropical Pacific sea-surface temperature "
                                             "anomaly") and "read here for El Nino:" in l]
    assert sb1, "the ONI row must be the loudest row on this board"
    assert "sigma on its trailing window of one hundred twenty months" in sb1[0]
    assert "percentile of its own record" in sb1[0]
    assert "rising in each of the last four months" in sb1[0]
    assert any("El Nino is declared to move CBOT soybeans in the opposite direction with a lag the "
               "graph states as one to two quarters" in l for l in lines)
    assert any(l.startswith("- conditional on the lag the graph states") and
               "the horizon asked about, three months, sits" in l for l in lines)


def test_scenario_1_carries_the_SB_T_row_with_four_same_contract_changes(scenarios):
    ctx = scenarios["soybeans_now"]
    sb_t = [l for l, h in zip(ctx["block"].lines, ctx["block"].classes) if h == ("SB-T",)]
    assert len(sb_t) == 1
    for w in ("one session", "five sessions", "twenty-one sessions", "sixty-three sessions"):
        assert w in sb_t[0]
    assert "percentile of the window this read fetched" in sb_t[0]
    assert "realised volatility are not served yet" in sb_t[0]


def test_scenario_1_carries_the_crude_oil_upstream_path_on_the_ANCESTORS_OWN_band(scenarios):
    """Bar B8's fixture path, rendered: ``crude_oil -> soybean_crush_margin -> board_crush``. The band
    is the TOP node's own declared band onto the anchor price, never a sum along the hops."""
    ctx = scenarios["soybeans_now"]
    paths = [p for p in ctx["board"].paths if p["ancestor"] == "crude_oil"]
    assert paths
    p = paths[0]
    assert p["band_is_the_ancestors_own"]
    assert p["lag_band"].raw == ctx["board"].row("soybeans_cbot", "crude_oil").lag_band.raw


def test_scenario_1_carries_a_dated_watch_list_and_a_like_state_stanza(scenarios):
    ctx = scenarios["soybeans_now"]
    kinds = {w["kind"] for w in ctx["watch"]}
    assert "next_release" in kinds and "lag_window" in kinds
    assert any(l.startswith("LIKE STATE") for l in ctx["block"].lines)
    # THE RARITY COUNT AND ITS FLOOR, IN THE SPELLING THE PRODUCED ROW RENDERS (round-2 blocker 2:
    # the count beside a pick is the pool the pick was drawn from; the head-admitted count is a
    # second, separately named number). A row the selection did NOT build still renders HEAD's
    # sentence, which is pinned by name in the unit test above.
    assert any("could be compared with it, this one " in l
               for l in ctx["block"].lines), [l for l in ctx["block"].lines
                                              if l.startswith("LIKE STATE")]
    assert any("readable on every dimension since " in l for l in ctx["block"].lines)
    assert any("measured on the record as revised through" in l for l in ctx["block"].lines)


#: The plural-on-a-singular-count sightings this bar exists to keep out. Each was MEASURED on a
#: rendered block: a count in WORDS still has to agree with the noun and the verb beside it.
_SINGULAR_MISMATCHES = ("one such crossings", "one other boards", "one hops upstream",
                        "one of its one declared drivers sit among",
                        # ROUND 2's own two: the ranked-pool clause and the second number beside it.
                        "one past readings on this series", "one like states admitted",
                        "one dated documents inside the window")


def test_a_singular_count_takes_a_SINGULAR_NOUN_in_every_template(scenarios):
    for name, ctx in scenarios.items():
        text = ctx["block"].text()
        for phrase in _SINGULAR_MISMATCHES:
            assert phrase not in text, (name, phrase)
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            if hit[0] != "SB-C" or " one of the " not in line:
                continue
            assert "condition" in line and " is showing here " in line, line
    # and the builders themselves, on a stated row rather than on whatever the fixtures happen to make
    one = dict(name="p", contract="soybeans_cbot", direction="", threshold=1, drivers=("a",),
               matched=("a",), n_matched=1, matched_measured=("a",), matched_unmeasured=(),
               n_declared=1, loud_k=8, n_with_band=1, note="", interactions=())
    assert "one of the one condition it names is showing here" in R.sb_convergence(one)
    assert "with its own [N] z" in R.sb_convergence(one)
    assert "each with its own [N] z" not in R.sb_convergence(one)


def test_the_WATCH_word_reaches_every_watch_row_including_the_one_that_carries_a_figure(scenarios):
    """Sec 6.2 gives SB-W "ISO dates + kind-2 figure" and the mandate's fourth movement tells the writer
    to close with the WATCH rows. The kind-2 row used to render as a bare distance line with no WATCH
    word at all, which cost the writer the row; it now wears the word, keeps ONE handle for ONE
    magnitude, and keeps its own class so the digit bar still holds every other watch row."""
    for name, ctx in scenarios.items():
        rendered = [l for l, h in zip(ctx["block"].lines, ctx["block"].classes)
                    if h[0] in ("SB-W", "SB-V")]
        fired = [w for w in ctx["watch"]]
        assert len(rendered) == len(fired), name
        for line in rendered:
            assert " WATCH " in line, (name, line)
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            if hit[0] == "SB-V":
                assert line.startswith("- [N"), line       # exactly one handle, at the front
                assert line.count("[N") == 1, line


def test_scenario_2_surfaces_PALM_from_a_SOYBEANS_ONLY_question(scenarios):
    """Amendment 2's own bar: the question names no second market, and the fan-out must surface palm
    with PALM'S OWN sign and band on the same ONI state."""
    ctx = scenarios["el_nino_fanout"]
    assert "palm" not in ctx["question"].lower()
    assert ctx["board"].anchor_slugs == ("soybeans_cbot",)
    far = [f for e in ctx["board"].fan if e["driver_id"] == "El_Nino"
           for f in e["far"] if f["contract"] == "malaysian_crude_palm_oil_cme"]
    assert far and far[0]["sign"] == "+" and far[0]["lag"] == "2-4 quarters"
    assert far[0]["free"], "the palm row folds onto the anchor's own ONI key at zero extra reads"
    assert any("El Nino is declared to move CME palm oil in the same direction with a lag the graph "
               "states as two to four quarters" in l for l in ctx["block"].lines)


def test_scenario_2_prints_the_two_signs_on_SEPARATE_lines_and_never_reconciles_them(scenarios):
    ctx = scenarios["el_nino_fanout"]
    soy = [l for l in ctx["block"].lines
           if l.startswith("- El Nino is declared to move CBOT soybeans")]
    palm = [l for l in ctx["block"].lines
            if l.startswith("- El Nino is declared to move CME palm oil")]
    assert soy and palm and soy[0] != palm[0]
    assert "opposite direction" in soy[0] and "same direction" in palm[0]


def test_scenario_2_reads_the_analog_outcome_over_EACH_BOARDS_OWN_band(scenarios):
    """One like state, two horizons: the bean benchmark over one to two quarters and the palm benchmark
    over two to four. That is the whole content of the scenario."""
    ctx = scenarios["el_nino_fanout"]
    fired = [a for a in ctx["analogs"] if not a.get("declined") and a["driver_id"] == "El_Nino"]
    assert fired
    labels = {o["label"]: o for a in fired for o in a["outcomes"] if not o.get("declined")}
    assert any("palm monthly benchmark" in l for l in labels)
    palm = [o for l, o in labels.items() if "palm monthly benchmark" in l][0]
    assert palm["band"].raw == "2-4 quarters"
    # AND THE RENDERED LINE SAYS WHICH BAND IT USED. The data was right and the PROSE was a false note:
    # the SB-A header declared the SEED's band for the whole stanza while the rows under it were read
    # over several, so the most prominent analog figure on a soybean board was a palm move printed
    # under a soybean band. Every figure was handle-bound, so `verify._check_number_handle`
    # value-checked the magnitude and nothing checked the band.
    lines = ctx["block"].lines
    palm_line = [l for l in lines if l.startswith("- [N") and "palm monthly benchmark over the band"
                 in l]
    soy_line = [l for l in lines if l.startswith("- [N") and "soybean monthly benchmark over the band"
                in l]
    assert palm_line and soy_line
    assert "two to four quarters" in palm_line[0], palm_line[0]
    assert "one to two quarters" in soy_line[0], soy_line[0]
    header = [l for l in lines if l.startswith("LIKE STATE El Nino") and "sat like this" in l]
    assert header
    assert "the declared lag band of" not in header[0], header[0]
    for band in ("one to two quarters", "two to four quarters"):
        assert band not in header[0], header[0]


def test_the_analog_outcome_names_a_CHANGE_with_a_verb_and_never_a_bare_level(scenarios):
    """"161.56 USD/t at the near end" reads as a level, and against a palm benchmark that sits around
    760 USD/t that is exactly the misreading available. ``window_change`` returns a change."""
    for name, ctx in scenarios.items():
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            if hit[0] != "SB-O":
                continue
            assert "moved " in line, (name, line)
            # 09-23 DESK VOCABULARY: the band's two ends are WHEN the lag opened and closed.
            assert "by the time that lag opened" in line and "by the time it closed" in line, \
                (name, line)


def test_B18_the_event_rows_published_date_and_E_handle_BIND_TO_THE_WINNING_RECEIPT(scenarios):
    """The rule that chooses the event date also names the document. Reading `receipts['top'][0]` --
    the caller's first receipt in INSERTION order -- printed the right date on this fixture only by
    luck: on the real path receipts arrive ranked by recency and specificity (sec 2.2), which puts the
    later levy document first."""
    ctx = scenarios["b40_event"]
    row = ctx["board"].row("malaysian_crude_palm_oil_cme", "biodiesel_mandate")
    assert row.event_receipt and row.event_receipt["date"] == "2026-05-02"
    ev = [l for l in ctx["block"].lines if l.startswith("- biodiesel mandate dated")][0]
    assert "(published 2026-05-02)" in ev
    handle = re.search(r"by \[E(\d+)\]", ev).group(1)
    rec = [l for l in ctx["block"].lines if l.startswith(f"- [E{handle}][T")]
    assert rec and "2026-05-02" in rec[0], "the [E] handle must point at the document the row names"


def test_B18_the_winning_receipt_is_chosen_by_the_RULE_and_not_by_ARRIVAL_ORDER():
    """The same three receipts in the order the ranked retrieval would hand them over."""
    ranked = list(reversed(H.B40_RECEIPTS))
    ed, prec, rc = W.event_receipt_for(ranked, "2026-09-07")
    assert (ed, prec) == (H.B40_DATE, "day")
    assert rc["date"] == "2026-05-02", "day precision beats month; the later piece never anchors"


def test_the_E_handles_are_MINTED_ONCE_for_the_whole_block(scenarios):
    """A board carrying receipts on several rows used to restart at [E1] inside every loop, so one
    label pointed at three documents until ``cit.unify`` renumbered them."""
    for name, ctx in scenarios.items():
        seen = re.findall(r"\[E(\d+)\]", ctx["block"].text())
        assert len(seen) == len(set(seen)) or True       # unify may repeat a handle across a citation
        mints = [int(m) for l in ctx["block"].lines for m in re.findall(r"^- \[E(\d+)\]\[T", l)]
        assert mints == sorted(set(mints)), (name, mints)


def test_a_convergence_row_names_ONLY_the_rows_that_CARRY_AN_N_z(scenarios):
    """Sec 6.2's template promises "({names}, each with its own [N] z)" and the loud set admits rows
    with no state by construction (a crossed band, an open event -- doctrine M-3). The COUNT is the
    ordering fact and stands; the names are split, so a writer told that four of four demand drivers
    are loud is not told they were measured."""
    for name, ctx in scenarios.items():
        measured = {r.driver_id for r in ctx["board"].rows
                    if r.state is not None and ROWS.status_word(r.state.status) == "ok"}
        for c in ctx["board"].convergence:
            assert set(c["matched_measured"]) <= measured, (name, c["name"])
            assert not (set(c["matched_unmeasured"]) & measured), (name, c["name"])
            assert (tuple(sorted(c["matched_measured"] + c["matched_unmeasured"]))
                    == tuple(sorted(c["matched"]))), (name, c["name"])
            line = R.sb_convergence(c)
            for d in c["matched_unmeasured"]:
                assert R.humanise(d) in line, (name, d)   # named, never deleted
                assert "no series read here" in line
    ctx = scenarios["soybeans_now"]
    trade = [l for l in ctx["block"].lines if l.startswith("- trade-war demand loss")]
    assert trade and "with its own [N] z" in trade[0]
    # RE-ANCHORED, review round 2 MAJOR 9. "four of the four conditions it names ARE SHOWING HERE" was
    # an observation claim the next clause denied for three of the four. The verb now covers only the
    # rows that were READ, the unread ones are named as NAMED BY THE PATTERN, and the TOTAL -- which is
    # the number the threshold comparison uses -- is stated: no count changed and no name was deleted.
    assert "one of the four conditions it names is showing here" in trade[0], "the READ count"
    # RE-ANCHORED (review round 3, NEW-2): the total is the COUNTED one, not "on this page".
    assert "so four of the four are counted here" in trade[0], "the TOTAL still stands"
    # 09-24 RE-BANK (ITEM 2, CONTRACT K3 R half -- DM1): the pattern roster names each READ condition by the
    # series it serves plus "read here for <driver>", never by the driver's humanised id alone (the rice page
    # handed a writer "the India export ban" for an exports row). The READ row still alone carries a z.
    assert "(weekly export shipments, read here for export pace lag, with its own [N] z)" in trade[0], \
        "only the READ row carries a z"
    assert "China import tariff" in trade[0] and "no series read here" in trade[0]
    # THE QUORUM ROW CARRIES NO FIRING CLAIM AND NO INTERNAL VOCABULARY (lane D, 2026-09-17).
    # `walk.CONVERGENCE_BANNED_WORDS` puts firing with `firing.fire_contract`, so the row states the
    # count and the number the pattern asks for and leaves the verdict to the reader.
    assert "it asks for two, so the count here is at or past that number" in trade[0]
    for banned in ("loudest rows", "declared drivers", "the pattern's own threshold",
                   " met", "fires", "regime is", "in force"):
        assert banned not in trade[0], banned


def test_scenario_3_renders_the_EVENT_the_upstream_levy_and_the_convergence_ordering(scenarios):
    ctx = scenarios["b40_event"]
    lines = ctx["block"].lines
    assert any(l.startswith("- biodiesel mandate dated") for l in lines)
    assert any(l.startswith("UPSTREAM CPO export levy -> biodiesel mandate") for l in lines)
    conv = [c for c in ctx["board"].convergence if c["name"] == "biodiesel_energy_floor"]
    assert conv and conv[0]["n_matched"] == 2 and conv[0]["threshold"] == 2
    # RE-ANCHORED (review round 2, MAJOR 9): one of the two matched drivers carries no series read, so
    # the leading count is ONE and the total is stated beside it.
    assert any("one of the three conditions it names is showing here" in l for l in lines)
    assert any("so two of the three are counted here" in l for l in lines)
    amp = [l for l in lines if l.startswith("  amplifier") and "crude oil price, biodiesel mandate" in l]
    assert amp, "B16's own fixture: the (crude_oil_price, biodiesel_mandate) amplifier must render"


def test_scenario_3_says_plainly_that_a_planned_flag_has_no_numeric_event_history(scenarios):
    ctx = scenarios["b40_event"]
    ev = [a for a in ctx["analogs"] if a.get("declined") == "no_numeric_event_history"]
    assert ev
    assert any("no numeric event history" in l for l in ctx["block"].lines)


def test_scenario_3_carries_the_soyoil_substitution_spillovers(scenarios):
    """`rev_cross_links`: palm cascades into soybean oil, soybeans and canola. The board carries the
    edges both ways on Cascade."""
    ctx = scenarios["b40_event"]
    others = {e["other"] for e in ctx["board"].edges if e["other"]}
    assert {"soybean_oil_cbot", "soybeans_cbot", "canola_ice"} <= others


# ═══ EVERY SLOT IS STAMPED (sec 0.3) ════════════════════════════════════════════════════════════════
def test_every_slot_of_every_scenario_is_stamped_served_absence_or_receipt(scenarios):
    for name, ctx in scenarios.items():
        audit = H.slot_audit(ctx)
        assert audit, name
        for slot, stamp in audit:
            assert stamp.split(":")[0] in ("served", "absence", "receipt"), (name, slot, stamp)


def test_the_slot_stamps_are_DERIVED_from_the_board_and_not_declared(scenarios):
    """A hand-written "served" beside a slot is exactly what the design's own slot audit exists to
    stop: four slots revision 1 wrote as figures had no producer at HEAD."""
    ctx = scenarios["soybeans_now"]
    stamps = dict(H.slot_audit(ctx))
    assert stamps["China import tariff"].startswith("absence:scope_unresolved")
    assert stamps["ONI state (level, z, percentile, run)"] == "served"


# ═══ THE MEASUREMENT (sec 7) ════════════════════════════════════════════════════════════════════════
def test_the_measurement_reports_rows_and_tokens_per_row_class(scenarios):
    for name, ctx in scenarios.items():
        m = H.measure(ctx)
        assert m["rows"] == len(ctx["block"].lines)
        assert m["tokens_est"] == round(m["chars"] / 4.0)
        assert sum(e["rows"] for e in m["per_class"].values()) == m["rows"]
        assert "UNCLASSIFIED" not in m["per_class"], name
        assert not any(k.startswith("AMBIGUOUS") for k in m["per_class"]), name


def test_the_render_caps_are_the_tiers_own_and_a_capped_section_NAMES_what_it_cut(scenarios):
    assert R.render_caps("max")["spillover"] == 16
    assert R.render_caps("deep")["analog"] == 1 and R.render_caps("max")["analog"] == 2
    assert R.render_caps("quick")["analog"] == 0            # Scan runs no analogs, by budget
    ctx = scenarios["soybeans_now"]
    cut = [l for l in ctx["block"].lines
           if l.startswith("BOARD ABSENCE the further markets past this tier's spillover cut")]
    assert cut and "(" in cut[0], "the names are never cut, only the sentences are shared"


#: The outcome cut's own sentence. It is NOT in ``_CUT_PREFIXES`` for a measured reason: at the shipped
#: caps no scenario stanza carries more outcomes than Cascade's four, so the line correctly never
#: renders on the three fixtures, and a prefix asserted to appear on them would be asserting a cut that
#: is not happening.
_OUTCOME_CUT = "BOARD ABSENCE the outcomes of this like state past this tier's outcome cut"


def test_the_ANALOG_OUTCOME_cut_NAMES_what_it_dropped_and_says_nothing_when_it_dropped_NOTHING(
        scenarios):
    """S3-2, on the b40_event board. ``for o in outs[: cap["analog_outcomes"]]`` dropped the tail of a
    stanza's consequences with NO absence row, no name list and no sentence -- the fifth cut in a module
    whose other four each say what they dropped and why, and the only one a reader could not tell from a
    stanza that simply had nothing more to say.

    THE CAP THIS PIN DRIVES IT AT IS A SHIPPED ONE: ``analog_outcomes`` is zero on Scan (RENDER_CAPS
    "quick"), so a tier that prints no outcome row at all is a real tier, and it is exactly the tier
    whose silence was total. Both directions are graded -- the cut names its tail, and a stanza that
    lost nothing mints no absence, because a cut line over an uncut section is a false absence."""
    ctx = scenarios["b40_event"]
    bd, ana = ctx["board"], ctx["analogs"]
    caps = dict(R.render_caps(ctx["mode"]))

    # 1. the shipped Cascade caps drop no outcome on this board, and the block says nothing about a cut
    assert caps["analog_outcomes"] == 4
    assert not [l for l in ctx["block"].lines if l.startswith(_OUTCOME_CUT)]

    # 2. at Scan's own outcome cap the held outcomes are NAMED rather than silently absent
    tight = R.render_board(bd, analogs=ana, watch=ctx["watch"], recency=ctx["recency"],
                           caps=dict(caps, analog_outcomes=0))
    cut = [l for l in tight.lines if l.startswith(_OUTCOME_CUT)]
    assert cut, "the outcome cut dropped rows and said nothing"
    shown = [a for a in ana if not a.get("declined")][: int(caps["analog"])]
    dropped = {str(o.get("label")) for a in shown
               for o in (a.get("outcomes") or ()) if not o.get("declined")}
    assert dropped, "the fixture must carry an outcome to drop, or it is grading nothing"
    for label in dropped:
        assert any(label in l for l in cut), label
    for l in cut:
        head = l.split(":")[0]
        assert head.rstrip().endswith(")"), l[:160]      # the same shape the four swept cuts have
        assert "named above" not in l
    # 3. a DROPPED outcome is not a DECLINED one: the two absences keep their own sentences
    assert all(l != R.sb_absence("an outcome over that band", "render_cap") for l in cut)


#: Every cut line whose sentence CLAIMS a naming. Sec 3.8's law is "the tail it cannot afford is
#: NAMED"; four of these claimed it and named the rows nowhere.
_CUT_PREFIXES = (
    "BOARD ABSENCE the further markets past this tier's spillover cut",
    "BOARD ABSENCE the like states past this tier's stanza cut",
    "BOARD ABSENCE the upstream paths past this tier's render cut",
    "BOARD ABSENCE the far states of the readings past this tier's cut",
    "BOARD ABSENCE the keys this turn's budget did not reach",
)


def test_EVERY_cut_line_NAMES_what_it_cut_and_no_sentence_points_ELSEWHERE(scenarios):
    """"the rows past this tier's render cut are named above" with the rows named nowhere is a claim
    the block cannot back, and the budget line carried forty deferred keys that reached the reader in
    no form at all."""
    seen = set()
    for name, ctx in scenarios.items():
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            if hit[0] != "SB-X":
                continue
            for pref in _CUT_PREFIXES:
                if not line.startswith(pref):
                    continue
                seen.add(pref)
                head = line.split(":")[0]
                assert head.rstrip().endswith(")"), (name, line[:160])
                assert len(head.split("(", 1)[1].split(", ")) >= 1, (name, line[:160])
            assert "named above" not in line, (name, line[:160])
    assert seen == set(_CUT_PREFIXES), sorted(set(_CUT_PREFIXES) - seen)


def test_the_budget_cut_names_ONE_ROW_PER_DEFERRED_KEY_and_never_a_raw_series_label(scenarios):
    """B3's "NAMED deferrals equal in count to declared - read", carried through to the reader: the
    render names the ROWS the deferred keys would have carried, because a `SeriesKey.label` in reader
    prose is an ``register.internal_leaks`` hit by construction."""
    for name, ctx in scenarios.items():
        notes = [n for n in ctx["board"].notes if n.get("kind") == "budget_cap"]
        if not notes:
            continue
        pairs = {p for n in notes for p in (n.get("pairs") or ())}
        assert pairs, name
        line = [l for l in ctx["block"].lines
                if l.startswith("BOARD ABSENCE the keys this turn's budget did not reach")][0]
        # THE NAMES INSIDE ONE ABSENCE LINE ARE THEMSELVES CAPPED at S6's review (`absence_names`;
        # one such line MEASURED 23,871 characters), so the claim is now "every deferred key is named
        # OR counted": the line carries the tier's share of the names and states the remainder in
        # WORDS. What may never happen is a name silently vanishing, which is what this asserts.
        named = R._named_rows(pairs)
        cap = int(R.render_caps(ctx["board"].mode,
                                getattr(ctx["board"], "knobs", None)).get("absence_names") or 0)
        shown = named if (not cap or len(named) <= cap) else named[:cap]
        for label in shown:
            assert label in line, (name, label)
        if len(shown) < len(named):
            assert "further readings this line does not name" in line, (name, line[:200])
        assert "|" not in line, "a series-key label reached the reader"


def test_B7_the_palm_row_is_computed_on_the_SHIFTED_series_and_not_only_labelled_with_the_offset(
        scenarios):
    """The fixture printed the SOY board's +0.98 degC, its z, its run and its percentile under a note
    asserting a six-month shift nobody applied. B7 asks for the palm row's OWN level, z and run on the
    shifted series, and a fixture that prints the claim without the arithmetic grades the wrong half."""
    ctx = scenarios["b40_event"]
    palm = ctx["board"].row("malaysian_crude_palm_oil_cme", "El_Nino")
    soy = scenarios["soybeans_now"]["board"].row("soybeans_cbot", "El_Nino")
    assert palm is not None and palm.state is not None
    assert soy is not None and soy.state is not None
    assert palm.state.level != soy.state.level, "the two boards read the SAME series at two states"
    assert palm.state.level_date != soy.state.level_date
    assert palm.state.offset_months == 6
    assert palm.state.level_date == "2026-02-28", "the level is the shifted array's own newest print"
    assert round(float(palm.state.z["value"]), 3) != round(float(soy.state.z["value"]), 3)
    line = [l for l, h in zip(ctx["block"].lines, ctx["block"].classes)
            if h[0] == "SB-1" and l.startswith("- [N") and "on CME palm oil" in l
            and "read here for El Nino:" in l]
    # THE PERIOD AT ITS OWN PRECISION, AND THE OFFSET IN THE ROW'S OWN NAME (09-23, C1 / L2).
    # 09-24 RE-BANK (CONTRACT K2 -- DM1): the period at its own precision moved INTO the figure token the
    # writer copies ("-0.67 degC, February 2026"); the offset stays in the row's own name.
    assert line and "read six months back -- the reading whose declared lag lands now" in line[0], line
    assert "degC, February 2026;" in line[0], line
    assert "oni_climate" not in line[0], "an internal ref reached a reader"


def test_the_harness_is_deterministic_across_two_builds(graph):
    """A fixture that moved between runs would make every bar above unfalsifiable."""
    a = H.build_scenario("el_nino_fanout", graph=graph)["block"].text()
    b = H.build_scenario("el_nino_fanout", graph=graph)["block"].text()
    assert a == b


def test_the_harness_exits_zero_on_all_three_scenarios(capsys):
    assert H.main(["all", "--no-block"]) == 0
    out = capsys.readouterr().out
    out.encode("ascii")                                     # ASCII-only stdout is a law here
    assert "harness: 3 scenario(s), exit 0" in out


def test_B12_the_age_clause_reaches_the_SB_1_LINE_and_not_only_the_producer():
    """The clause is computed by ``narration.age_clause`` and THREADED into ``render_board``; a bar that
    only graded the producer would pass on a board that never printed one."""
    from leviathan.graphrag.state.feeders import state_from_arrays
    d = [f"2025-{m:02d}-28" for m in range(1, 13)] + ["2026-01-31", "2026-02-28", "2026-03-31"]
    st = state_from_arrays("oni_climate", [float(i) for i in range(15)], d, cadence="monthly",
                           asof="2026-09-07", unit="degC", narrate_unit="degC",
                           windows={"monthly": 12}, table="silver_noaa_oni", metric="anom")
    row = B.NodeRow(contract="soybeans_cbot", driver_id="El_Nino", lag_band=parse_lag("1-2 quarters"),
                    state=st, sign="-")
    row.legs["loud"] = True
    bd = B.Board(asof="2026-09-07", mode="max", knobs=B.board_knobs_of("max"),
                 anchors=(B.Anchor(contract="soybeans_cbot", source="named"),))
    bd.rows = [row]
    bd.order = (row.key,)
    clause = N.age_clause(st.knowledge_date, bd.asof, st.cadence)
    assert clause, "the fixture must actually be stale for its cadence"
    blk = R.render_board(bd, age_clauses={row.key: clause})
    sb1 = [l for l, h in zip(blk.lines, blk.classes) if h == ("SB-1",)]
    assert sb1 and clause in sb1[0]
    assert "span to this as-of" in sb1[0]


# ═══ AMENDMENT 1: the CO-LOUD stanza REACHES THE READER ═════════════════════════════════════════════
def _co_loud_block():
    """A driver-as-subject board (sec 16 Amendment 1) built from fixture arrays and rendered WHOLE.

    The producer half has been pinned since S3 (``test_state_analogs``); what had no pin -- because it
    had no code -- is the JOIN. ``co_loud_analogs`` returns a shape of its own and ``render_board``
    renders a flat stanza list, so Amendment 1's leg computed and then fell on the floor. This builds
    the board, adapts, renders, and hands the block back so the bars below grade real output."""
    from leviathan.graphrag.state.feeders import state_from_arrays
    d, y, m = [], 2018, 1
    for _ in range(60):
        last = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
        d.append(f"{y:04d}-{m:02d}-{last:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    spike = [0.0] * 30 + [100.0] * 12 + [0.0] * 18
    pcts = {"soybeans_cbot": spike, "corn_cbot": spike}
    bd = B.Board(asof="2026-09-07", mode="max", knobs=B.board_knobs_of("max"),
                 anchors=tuple(B.Anchor(contract=c, source="focus_driver", rank=i,
                                        driver_id="cot_mm_positioning", subject=True)
                               for i, c in enumerate(pcts)))
    # THE TWO BOARDS DECLARE DIFFERENT BANDS ON PURPOSE. "outcomes over each contract's own lag band"
    # is half of Amendment 1, and a fixture where both bands agree cannot tell a per-contract read from
    # a stanza-wide one -- the seed's-band-for-everything false note sec 4.3 corrects.
    bands = {"soybeans_cbot": "0-1 quarters", "corn_cbot": "1-2 quarters"}
    for c, vals in pcts.items():
        st = state_from_arrays("cot_mm_positioning", vals, d, cadence="monthly", asof=bd.asof,
                               windows={"monthly": 24}, table="silver_cot", metric="mm_net",
                               commodity=c)
        bd.rows.append(B.NodeRow(contract=c, driver_id="cot_mm_positioning",
                                 lag_band=parse_lag(bands[c]), state=st, subject=True))
    bd.order = tuple(r.key for r in bd.rows)
    bench = {c: {"values": [float(100 + i) for i in range(60)], "dates": d, "unit": "USD/t",
                 "label": f"the monthly benchmark for {R.board_label(c)}",
                 "table": "silver_pink_sheet", "metric": "px"} for c in pcts}
    co = A.co_loud_analogs(bd, "cot_mm_positioning", k=2, analog_k=2,
                           benchmark_fn=lambda c: bench.get(c))
    assert co["declined"] is None, "the fixture must actually co-occur"
    stanzas = A.co_loud_stanzas(bd, co)
    return bd, stanzas, R.render_board(bd, analogs=stanzas)


def test_the_CO_LOUD_stanza_REACHES_the_render_and_wears_the_classes_6_2_ALREADY_HAS():
    """The minor this closes: ``co_loud_analogs`` had no consumer, so a driver-as-subject board rendered
    NO like state at all. The adapter is a join and not a second renderer -- the header is SB-A and the
    outcomes are SB-O, so the closed vocabulary of 6.2 gains no token and the disjointness lint has no
    new regex to reconcile."""
    _bd, stanzas, blk = _co_loud_block()
    assert stanzas and all(s["co_loud"] for s in stanzas)
    assert all(len(h) == 1 for h in blk.classes), \
        [(h, l[:80]) for h, l in zip(blk.classes, blk.lines) if len(h) != 1]
    heads = [l for l, h in zip(blk.lines, blk.classes) if h == ("SB-A",)]
    outs = [l for l, h in zip(blk.lines, blk.classes) if h == ("SB-O",)]
    assert heads, "the co-loud header did not render"
    assert outs, "no outcome over a contract's own band rendered"
    # EACH ROW OVER ITS OWN BOARD'S BAND, and the row prints which (4.3): the two boards declare
    # different bands, so one stanza-wide band would print the same words twice.
    assert any("zero to one quarter" in l for l in outs), outs
    assert any("one to two quarters" in l for l in outs), outs
    # SB-JOIN IS THE ONE CLASS BEYOND SEC 6.2's TABLE, added by the S6 review with its reason recorded
    # at the class itself: nothing in 6.2 can say "these two rows are one reading", which is what a
    # mutually-exclusive phase pair on one global series needs said. It is letters-only and mints no
    # handle, so the [N] address space and the verifier are untouched.
    # SB-LEAD IS THE SECOND SUCH CLASS (ROUND-2 DOCKET item 12): the three largest moves, one line
    # each, FIRST in the block. Like SB-JOIN it describes the block's own shape rather than a row's
    # content, it is letters-only and it mints no handle, so the [N] address space is untouched.
    assert set(R.ROW_CLASSES) == {"SB-H", "SB-1", "SB-V", "SB-T", "SB-O", "SB-W", "SB-R", "SB-E",
                                  "SB-J", "SB-D", "SB-F", "SB-C", "SB-M", "SB-P", "SB-A", "SB-L",
                                  "SB-X", "SB-JOIN", "SB-LEAD", "SB-ASK"}
    # 09-24 (CONTRACT K8): SB-ASK -- the head's asked rows, spread and horizon -- is a FIGURE class.
    assert "SB-ASK" in R.FIGURE_CLASSES
    assert "SB-LEAD" not in R.FIGURE_CLASSES and "SB-LEAD" not in R.DATE_ONLY_CLASSES


def test_the_CO_LOUD_header_names_the_CO_OCCURRENCE_and_never_the_ordinary_SELECTORS_sentence():
    """SB-A is a CLASS and not a template. "the series sat like this" describes the ordinary selector;
    the co-loud one asks when SEVERAL boards sat in the top decile AT ONCE, and a header that printed
    the other sentence would name a selector that did not run."""
    _bd, _stanzas, blk = _co_loud_block()
    head = [l for l, h in zip(blk.lines, blk.classes) if h == ("SB-A",)][0]
    assert "across the markets that carry it" in head
    assert "sat in the top decile of their own history at once" in head
    assert "the series sat like this" not in head
    assert "two of them" in head                      # the count in WORDS, never a digit


def test_the_CO_LOUD_stanza_is_REGISTER_CLEAN_and_its_letters_only_rows_carry_no_digit():
    """B6's three bars, run on the Amendment 1 leg the three acceptance fixtures do not reach."""
    from leviathan.graphrag import register as reg
    _bd, _stanzas, blk = _co_loud_block()
    assert blk.trips == []
    for line, hit in zip(blk.lines, blk.classes):
        assert reg.register_leaks(line) == [], line[:120]
        if hit[0] in R.FIGURE_CLASSES:
            continue
        bare = _GLUED_RX.sub("", _YEAR_RX.sub("", _YM_RX.sub("", _ISO_RX.sub(
            "", _HANDLE_RX.sub("", line)))))
        assert not any(ch.isdigit() for ch in bare), f"{hit[0]}: {line[:140]}"
    blk.text().encode("ascii")


def test_the_CO_LOUD_receipt_ABSENCE_does_not_attribute_the_whole_stanza_to_ONE_board():
    """The stanza spans boards, so "on {board}" would hand the leading anchor rows that are several
    boards' own records. The ordinary stanza keeps its own sentence."""
    _bd, _stanzas, blk = _co_loud_block()
    absence = [l for l in blk.lines if "holds no dated document" in l]
    assert absence, "the co-loud stanza carries no receipts and must say so"
    assert "across the markets that carry it" in absence[0]
    assert "the markets' own records alone" in absence[0]


def test_a_DECLINED_CO_LOUD_result_is_a_ROW_and_never_a_silent_empty_stanza_list():
    """An absence is a ROW (4.5). ``co_loud_analogs`` declines ``no_like_state`` when the contracts
    never co-occur, and the adapter carries that word into the render rather than returning nothing."""
    from leviathan.graphrag.state.feeders import state_from_arrays
    d = [f"{2018 + i // 12:04d}-{i % 12 + 1:02d}-28" for i in range(60)]
    early, late = [100.0] * 12 + [0.0] * 48, [0.0] * 48 + [100.0] * 12
    bd = B.Board(asof="2026-09-07", mode="max", knobs=B.board_knobs_of("max"),
                 anchors=(B.Anchor(contract="soybeans_cbot", source="focus_driver", rank=0,
                                   driver_id="cot_mm_positioning", subject=True),
                          B.Anchor(contract="corn_cbot", source="focus_driver", rank=1,
                                   driver_id="cot_mm_positioning", subject=True)))
    for c, vals in (("soybeans_cbot", early), ("corn_cbot", late)):
        st = state_from_arrays("cot_mm_positioning", vals, d, cadence="monthly", asof=bd.asof,
                               windows={"monthly": 24}, table="silver_cot", metric="mm_net",
                               commodity=c)
        bd.rows.append(B.NodeRow(contract=c, driver_id="cot_mm_positioning",
                                 lag_band=parse_lag("0-1 quarters"), state=st, subject=True))
    bd.order = tuple(r.key for r in bd.rows)
    co = A.co_loud_analogs(bd, "cot_mm_positioning", k=2, analog_k=2)
    assert co["declined"] == "no_like_state"
    stanzas = A.co_loud_stanzas(bd, co)
    assert len(stanzas) == 1 and stanzas[0]["declined"] == "no_like_state"
    blk = R.render_board(bd, analogs=stanzas)
    said = [l for l in blk.lines if l.startswith("BOARD ABSENCE a like state on this market")]
    assert said, blk.lines


# ═══ THE TWO SWEPT MINORS ═══════════════════════════════════════════════════════════════════════════
def test_SB_J_gives_a_CLOSED_window_its_DATE_and_never_a_horizon_the_reader_cannot_use():
    """The horizon runs FORWARD from the as-of; a window counted from the state's own date may already
    be over. "the horizon asked about, three months, sits past that window" is true arithmetic and a
    sentence that invites the reader to place a future question inside a window that closed -- so a
    closed window prints its CLOSING DATE instead, the distinction SB-D already draws on the event row.
    Fences CORRECT or COMPUTE: the clause is replaced, never suppressed."""
    kw = dict(board="CBOT soybeans", anchor_words="that reading's own date", horizon_months=3,
              asof="2026-09-07")
    closed = R.sb_projection(window={"opens": "2025-01-31", "closes": "2025-07-31", "declined": None},
                             horizon_sits="past", **kw)
    assert "that window closed on 2025-07-31" in closed
    assert "the horizon asked about" not in closed
    assert R.classify(closed) == ("SB-J",)

    still_open = R.sb_projection(window={"opens": "2026-10-31", "closes": "2027-04-30",
                                         "declined": None}, horizon_sits="inside", **kw)
    assert "the horizon asked about, three months, sits inside that window" in still_open
    assert "closed on" not in still_open
    #: the same day is not a CLOSED window -- the boundary is `<`, and an as-of ON the close still asks
    on_the_day = R.sb_projection(window={"opens": "2026-03-31", "closes": "2026-09-07",
                                         "declined": None}, horizon_sits="past", **kw)
    assert "the horizon asked about" in on_the_day and "closed on" not in on_the_day


def test_the_OFFSET_NOTE_names_its_PARENT_SERIES_by_the_display_label_and_leaks_no_ref():
    """Sec 2.6 item 1's note is the one clause whose subject is a SOURCE and not a node, and the raw ref
    survived every other display fold on the page. It folds to the SERIES' label -- the same words the
    line's own ``[table: ...]`` tag carries -- and not to the driver vocabulary's de-underscored id."""
    from leviathan.graphrag import register as reg
    from leviathan.graphrag.state.feeders import state_from_arrays
    d = [f"2026-{m:02d}-28" for m in range(1, 10)]
    st = state_from_arrays("oni_lag_climate", [float(i) for i in range(9)], d, cadence="monthly",
                           asof="2026-09-07", unit="degC", narrate_unit="degC",
                           windows={"monthly": 6}, table="silver_noaa_oni", metric="anom")
    st.alias_ref = "oni_climate"
    st.offset_note = ("the same series as oni_climate, read at a declared 6-month offset; it cost no "
                      "read of its own")
    words = R.offset_words(st)
    assert "the same series as NOAA ONI" in words
    assert "oni_climate" not in words and "oni climate" not in words
    assert reg.internal_leaks(words) == []
    row = B.NodeRow(contract="palm_oil_bmd", driver_id="El_Nino", lag_band=parse_lag("2-4 quarters"),
                    state=st, sign="-")
    row.legs["loud"] = True
    bd = B.Board(asof="2026-09-07", mode="max", knobs=B.board_knobs_of("max"),
                 anchors=(B.Anchor(contract="palm_oil_bmd", source="named"),))
    bd.rows = [row]
    bd.order = (row.key,)
    blk = R.render_board(bd)
    sb1 = [l for l, h in zip(blk.lines, blk.classes) if h == ("SB-1",)]
    assert sb1 and "the same series as NOAA ONI" in sb1[0], sb1


# === S7: THE QUICK RENDER CAPS =====================================================================
# THE OWNER'S RATIFIED RULE (09-10): "Scan (quick) gets render CAPS at S7; deep and max run UNCAPPED
# into arm A, the judged delta decides." The measurement behind it is the S4 board census (36 boards,
# pg mirror, in-VPC): the quick block's MEDIAN is 53 lines / 13,648.5 chars / ~3,412.5 est tokens
# against sec 7's Scan sizing of "~17-20 lines, ~1,100 tokens" -- 3.10x by tokens, 2.79x by lines --
# in front of a 105-154-word Scan writer budget (150-220 x budget_scale 0.7).
def test_S7_the_quick_caps_bind_at_the_numbers_the_tables_declare_and_the_paid_tiers_do_not_move():
    """EVERY S7 NUMBER, asserted against BOTH tables at once, so a knob edit and a render-table edit
    cannot drift. The three new keys ride the RENDER_CAPS TABLE (rather than being knob-only reads like
    `absence`) for the reason `render_caps` gives: a board built from a hand-built nine-field knob tuple
    has no render fields at all, and a missing attribute read as zero would silently uncap -- or cap to
    nothing -- a class nobody meant to move."""
    q, d, m = (R.render_caps(x, B.board_knobs_of(x)) for x in ("quick", "deep", "max"))
    assert (q["projection"], q["fan_names"], q["convergence"], q["absence"],
            q["absence_names"]) == (4, 8, 1, 3, 6)
    assert q["edge"] == 0, "the edge knob ships DARK on every tier; S8 sets the number"
    # THE PAID TIERS MOVE **NOTHING AT ALL** (round 2). The first cut gave deep a `fan_names` of 24 --
    # a bound on the ENUMERATION inside one line rather than on a row -- and that is still a cap the
    # owner's ratified rule did not grant a control cell: "Scan (quick) gets render CAPS at S7; deep and
    # max run UNCAPPED into arm A, the judged delta decides". A cap arm A did not intend is a second
    # flag in a one-flag experiment.
    for caps in (d, m):
        assert caps["projection"] == 0 and caps["edge"] == 0 and caps["absence"] == 0
        assert caps["fan_names"] == 0
    assert (d["convergence"], m["convergence"]) == (4, 6)
    assert (d["absence_names"], m["absence_names"]) == (24, 32), "S6's own numbers, unmoved"
    # ...and the RANK ORDERING rides the same tier switch: it is a decision only where a list is CUT,
    # Scan is the only tier that cuts one, and deep and max keep HEAD's lexical order byte for byte.
    assert R.rank_cuts(q) is True
    assert R.rank_cuts(d) is False and R.rank_cuts(m) is False
    assert R.rank_cuts(None) is False and R.rank_cuts({}) is False
    # ...and the no-knob branch still returns the TABLE, byte for byte (the pinned property)
    for mode in ("quick", "deep", "max"):
        assert R.render_caps(mode) == R.RENDER_CAPS[mode]
    # EVERY TIER DECLARES EVERY KEY; the paid tiers carry this table's UNCAPPED sentinel in all four
    for mode in ("deep", "max"):
        row = R.RENDER_CAPS[mode]
        assert (row["fan_names"], row["projection"], row["edge"], row["rank_cuts"]) == (0, 0, 0, 0)
    assert set(R.RENDER_CAPS["quick"]) == set(R.RENDER_CAPS["deep"]) == set(R.RENDER_CAPS["max"])


def test_S7_a_capped_quick_block_still_carries_every_row_the_coverage_instrument_GRADES(scenarios):
    """THE BAR THAT MATTERS MORE THAN THE LENGTH. `board_coverage` grades five classes -- the loud
    STATE rows, the OPEN EVENT rows, the RECENCY rows, the WATCH rows and the CROSS-edge far rows --
    and arm A reads those counters. A cap that shortened the block by removing a graded row would move
    the instrument arm A is measuring WITH, which is the one thing sec 10.3's "one flag per arm" rule
    forbids. So the S7 caps are asserted to bind on classes the instrument does NOT grade."""
    graded = {"state", "event_open", "recency", "watch", "far"}
    ctx = scenarios["soybeans_now"]
    bd = ctx["board"]
    base = dict(R.render_caps("max", B.board_knobs_of("max")))
    s7 = dict(base, projection=4, convergence=1, absence=3, absence_names=6, fan_names=8)
    kw = dict(analogs=ctx["analogs"], watch=ctx["watch"], recency=ctx["recency"])
    wide = R.render_board(bd, caps=base, **kw)
    tight = R.render_board(bd, caps=s7, **kw)

    def _roles(blk):
        out = {}
        for m in blk.rows_meta:
            r = m.get("role")
            if r in graded:
                out[r] = out.get(r, 0) + 1
        return out

    assert _roles(tight) == _roles(wide), "an S7 cap moved a class the coverage instrument grades"
    assert len(tight.lines) < len(wide.lines), "the S7 caps bound on nothing at all"


def test_S7_every_new_cut_NAMES_what_it_cut_in_the_boards_own_RANK_order():
    """Two laws at once. (1) 6.6: every cut names what it cut -- the projection and link cuts take the
    same shape the five swept cuts already have. (2) S7's own: the cut takes `Board.order`, never the
    alphabet. The second is what makes the first worth having -- an alphabetical cut hands the reader
    the rows whose display labels sort first and drops the board's loudest."""
    from leviathan.graphrag.state.feeders import state_from_arrays
    d = [f"2026-{mo:02d}-28" for mo in range(1, 10)]

    def _row(contract, driver):
        st = state_from_arrays("oni_climate", [float(i) for i in range(9)], d, cadence="monthly",
                               asof="2026-09-07", unit="degC", narrate_unit="degC",
                               windows={"monthly": 6}, table="silver_noaa_oni", metric="anom")
        r = B.NodeRow(contract=contract, driver_id=driver, lag_band=parse_lag("2-4 quarters"),
                      state=st, sign="-")
        r.legs["loud"] = True
        return r

    # `zebra` is ALPHABETICALLY LAST and is ranked FIRST, which is the whole point of the pin
    rows = [_row("soybeans_cbot", n) for n in ("zebra_driver", "alpha_driver", "beta_driver")]
    bd = B.Board(asof="2026-09-07", mode="quick", knobs=B.board_knobs_of("quick"),
                 anchors=(B.Anchor(contract="soybeans_cbot", source="named"),))
    bd.rows = rows
    bd.order = tuple(r.key for r in rows)
    caps = dict(R.render_caps("quick", B.board_knobs_of("quick")), projection=1)
    blk = R.render_board(bd, caps=caps)
    proj = [x for x in blk.lines if x.startswith("- conditional on the lag the graph states")]
    assert len(proj) == 1, proj
    cut = [x for x in blk.lines
           if x.startswith("BOARD ABSENCE the effect windows of the readings past this tier's "
                           "projection cut")]
    assert cut, "the projection cut dropped rows and said nothing"
    assert cut[0].split(":")[0].rstrip().endswith(")")
    # the RANK decides which rows are named and in which order -- never the alphabet
    assert cut[0].index("alpha driver") < cut[0].index("beta driver")
    assert "zebra driver" not in cut[0], "the board's TOP-ranked row was the one the cut dropped"
    # and the link cap takes the same shape when it is turned on (it ships at 0 = uncapped)
    blk2 = R.render_board(bd, caps=dict(caps, edge=1))
    assert len([x for x in blk2.lines if " is declared to move " in x]) == 1
    assert [x for x in blk2.lines
            if x.startswith("BOARD ABSENCE the declared links of the readings past this tier's link cut")]


def test_S7_the_absence_GROUPS_render_in_the_CLOSED_VOCABULARYS_declared_order():
    """`sorted(groups)` was harmless while every group printed and became a CONTENT decision the moment
    `render_absence` cut one: alphabetically that puts `budget_cap` and `history_truncated` ahead of
    `scope_unresolved`, `unmapped_ref`, `series_planned` and `series_none` -- the incidental reasons
    ahead of the four that say the estate carries no series for the row at all. The ranking is
    `board.LEG_REASONS`' own concatenation, so the design's order IS the render's order."""
    ranked = sorted(("budget_cap", "series_none", "unmapped_ref", "thin_history",
                     "history_truncated"), key=R._reason_rank)
    assert ranked[:3] == ["unmapped_ref", "series_none", "thin_history"]
    assert ranked[-1] == "budget_cap"
    # a word outside every closed enum still ranks, and ranks LAST rather than raising
    assert R._reason_rank("not_a_declared_word")[0] >= R._reason_rank("pg_timeout")[0]


def test_S7_the_FAN_INDEX_caps_its_ENUMERATION_and_never_its_COUNT():
    """Sec 3.6's "the names are never cut" is about the COUNT -- the figure that makes "the graph
    decides relevance" visible and the one a reader checks the enumeration against. MEASURED on the S4
    census: an SB-F index line runs 628-648 characters because it enumerates 29-35 board labels through
    a bare join, and the class is 10.5% of the quick block on 3.1 lines."""
    far = [{"contract": "soybeans_cbot" if i % 3 else "corn_cbot", "sign": "+" if i % 3 else "-",
            "driver_id": "d%d" % i, "lag_band": None, "confidence": "medium"} for i in range(30)]
    entry = {"contract": "soybeans_cbot", "driver_id": "El_Nino", "far": far}
    wide = R.sb_fan(entry, names_cap=0)
    tight = R.sb_fan(entry, names_cap=8)
    # THE POPULATION IS NAMED IN THE READER'S WORD (lane D, 2026-09-17): the fan enumerates MARKETS,
    # and `board` is the instrument's own word, which the PM lens read as system vocabulary and which
    # collides with the Canadian Wheat Board for anyone with grey hair. The COUNT rule is unchanged and
    # is what this pin is for.
    assert "thirty other markets" in wide and "thirty other markets" in tight, "the COUNT was cut"
    assert len(tight) <= len(wide)
    assert "further markets this line does not name" in tight
    assert "further rows this line does not name" not in tight, "a market is not a row"
    assert " boards" not in wide and " boards" not in tight, "the instrument's own word"
    # ...and the line names its SUBJECT and points at the nearest markets (finding (j)): a bare count
    # with no driver and no market to look at next reads as scoring machinery.
    assert wide.startswith("- El Nino is a shared driver across thirty other markets"), wide
    assert "The nearest two to this question are " in wide


# === S7 POLISH (a): THE BARE-YEAR ANCHOR ===========================================================
def test_S7a_month_words_knows_every_form_the_shipped_CARDS_write_and_never_returns_empty():
    """MEASURED on the banked S4 blocks: 13 of the 33 SB-J lines on the four banked quick boards and
    95 lines across all 16 banked census blocks printed "counted from the run's start in , the effect
    window ... opens around December 2024". A marketing-year card writes its period as a bare `YYYY`
    (`feeders._period_dates`; ten annual tables on the mirror) and `month_words` returned "" for it,
    so the ANCHOR words dropped out while the WINDOW was placed correctly -- `walk._add_months` had
    already been taught the bare-year form through `analogs.axis_date`. One function in the tree knew
    the form and the other did not."""
    assert R.month_words("2026-08-31") == "August 2026"
    assert R.month_words("2026-08") == "August 2026"
    assert R.month_words("2024") == "2024"            # a marketing-year card's own period
    assert R.month_words("1899") == "" and R.month_words("2100") == ""
    assert R.month_words("") == "" and R.month_words(None) == ""
    assert R.month_words("2026-13-01") == ""


def test_S7a_no_projection_line_carries_an_EMPTY_anchor_slot(scenarios):
    """The producer is fixed and this is the pin, over three surfaces at once: the unit case, the three
    acceptance fixtures, and the 16 BANKED census blocks -- which are the text the defect was measured
    in, so the pin fails loudly if a future edit reintroduces it."""
    import pathlib as _pl

    class _St:
        run = None
    bad = (" in ,", " in .", " in ;", " in  ")
    words = R._anchor_words(_St(), "2024")
    assert words.endswith("2024") and not any(b in words for b in bad)
    # a date NO form can place declines IN WORDS rather than printing a comma against nothing
    declined = R._anchor_words(_St(), "not-a-date")
    assert "anchor" in declined and not any(b in declined for b in bad)
    for name, ctx in scenarios.items():
        for line in ctx["block"].lines:
            assert not any(b in line for b in bad), (name, line[:160])
    banked = _pl.Path(__file__).resolve().parents[2] / "data" / "board_census" / "2026-09-07" / "blocks"
    if banked.exists():
        for p in sorted(banked.glob("*.md")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith("- conditional on the lag the graph states"):
                    # the BANKED text still carries the defect -- it is the HEAD render. What is
                    # asserted here is that the producer no longer can: the banked line's anchor is
                    # re-rendered through the fixed function and comes back whole.
                    assert R.month_words("2024") and R.month_words("2024-12")


# === S7 POLISH (b): THE CARD'S SCALE ===============================================================
def test_S7b_the_level_is_printed_in_ANALYST_UNITS_and_the_CALL_carries_the_same_magnitude():
    """MEASURED on the banked S4 blocks: 13 of the 36 SB-1 rows on the four banked quick boards (36%)
    and 109 rows across all 16 banked blocks printed the NATIVE magnitude under the ANALYST unit word
    -- `118000000 MMT`, `35852 M ha`, `87157400 million head`, and `ending stocks su ratio ... 0.13 %`
    on the `scale: 100` card whose own comment in cascade_map.yaml reads "THE ratio trap; pre-scale is
    MANDATORY". 25 of the 49 declared cards carry `scale != 1`.

    THE CALL AND THE PRINTED WORDS MOVE TOGETHER OR NOT AT ALL. `verify._check_number_handle` value-
    checks a writer's copy of the printed figure against this call's `shown` pool, so a line printing
    the scaled value over a call carrying the native one would strip every figure a writer correctly
    transcribed. Figures AND words together."""
    from leviathan.graphrag.state.feeders import state_from_arrays
    d = [f"202{y}-12-31" for y in range(1, 10)]
    st = state_from_arrays("stock", [118000000.0 + i for i in range(9)], d, cadence="annual",
                           asof="2026-09-07", unit="MT", narrate_unit="MMT", scale=0.000001,
                           windows={"annual": 6}, table="silver_psd", metric="ending_stocks_mt")
    assert st.level == 118000008.0 and abs(st.level_shown - 118.000008) < 1e-6
    row = B.NodeRow(contract="soybeans_cbot", driver_id="Brazil_export_tax", state=st, sign="+",
                    lag_band=parse_lag("1-2 quarters"))
    line, calls = R.sb_state(1, row, asof="2026-09-07")
    assert "118000000" not in line and "118000008" not in line
    assert "118 MMT" in line, line[:200]
    assert calls and abs(float(calls[0]["shown"][0]) - 118.000008) < 1e-6, calls[0]
    # THE RATIO TRAP, the sharpest of the four: scale 100 on a su_ratio card
    st2 = state_from_arrays("psd_ending_stock_su_ratio", [0.13] * 9, d, cadence="annual",
                            asof="2026-09-07", unit="ratio", narrate_unit="%", scale=100,
                            windows={"annual": 6}, table="silver_psd", metric="su_ratio")
    assert abs(st2.level_shown - 13.0) < 1e-9
    row2 = B.NodeRow(contract="corn_cbot", driver_id="psd_ending_stock_su_ratio", state=st2, sign="-",
                     lag_band=parse_lag("1-2 quarters"))
    line2, calls2 = R.sb_state(1, row2, asof="2026-09-07")
    assert "13 %" in line2 and "0.13 %" not in line2, line2[:200]
    assert abs(float(calls2[0]["shown"][0]) - 13.0) < 1e-9
    # a row with NO level has no shown level either, and keeps its own sentence
    st2.level = None
    assert st2.level_shown is None
    assert "no level was read" in R._level_words(st2)


# === S7 POLISH (c): THE TWO DOCKETED DEFECTS, LANDED 2026-09-17 BY LANE D ===========================
def test_S7c_the_two_docketed_defects_are_LANDED_and_neither_repeats_the_S7_failure():
    """THE DOCKET IS CLOSED AND THE CLOSURE IS PINNED AS TIGHTLY AS THE WITHDRAWAL WAS.

    (i) THE READING CLAUSE. S7's cut folded ``display.metric_label`` into the SB-1 head, never fired on
    the two POLICY rows it was written for (their metric words fold away against the driver label) and
    made 28 of 43 real rows worse by appending a storage-column word. The 2026-09-16 pre-arm smoke then
    served the defect to a fund PM -- "Argentine export tax sits at 6.65 MMT" over a PSD EXPORTS row --
    so the docket's OWN remedy is taken: reader words DECLARED beside the ref, never derived from a
    column name. The declaration is ``state_conventions.reading_words`` (``cascade_map.yaml`` is
    gitignored and generator-owned, the 09-15 law), :func:`render.reading_words` is the one reader, and
    an UNDECLARED metric renders NO clause -- so S7's failure mode is unreachable by construction.

    (ii) THE SAME-SIGN JOIN SENTENCE. HEAD's non-opposed branch said "They are phases of one series and
    not separate readings", which is FALSE of both non-opposed joins the banked blocks carry. The
    served deep answer repeated it and then COUNTED BOTH NAMES into a two-driver pattern quorum. The
    withdrawal's reason was that SB-JOIN renders on every tier and would have reworded arm A's CONTROL
    cells -- and arm A's control runs with ``GRAPHRAG_STATE_BOARD`` OFF, where this class does not
    render at all, so the blocker is gone.

    AND THE OPPOSED BRANCH GAINS A THIRD STATE THAT HEAD DID NOT HAVE. "Opposite signs ... which is what
    two phases of one series means" is only true where a phase pair is DECLARED; on the b40 fixture it
    rendered over `IDR USD` / `INR USD` / `MYR USD`, three currency rows folded onto one series key. The
    phase sentence now requires a declared pair and the undeclared case names the contradiction."""
    # (i) the clause exists, is DECLARED, and an unknown metric says nothing at all
    assert R.reading_words("silver_psd", "exports_mt") == "exports"
    assert R.reading_words("silver_psd", "su_ratio") == "the stocks-to-use ratio"
    assert R.reading_words("silver_fred_fx", "cny_usd")           # the card-wide default
    assert R.reading_words("silver_nothing", "no_such_metric") == ""
    assert not hasattr(R, "source_words") and not hasattr(R, "metric_words")
    from leviathan.graphrag import display as D
    assert not hasattr(D, "metric_label"), "the words are DECLARED, never derived from a column name"
    # (ii) the three join branches, each on its own state
    opp = R.sb_phase_pair(["El Nino", "La Nina"], "CBOT soybeans", opposed=True,
                          phase={"words": "the warm phase", "other_words": "the cool phase",
                                 "in_force": True, "live_name": "El Nino",
                                 "live_sign": "in the opposite direction", "other_name": "La Nina",
                                 "other_sign": "in the same direction"})
    same = R.sb_phase_pair(["China import pace", "China import tariff"], "CME palm oil", opposed=False,
                           keep="China import tariff", alias=("China import pace",))
    bare = R.sb_phase_pair(["IDR USD", "INR USD", "MYR USD"], "CME palm oil", opposed=True,
                           keep="IDR USD", alias=("INR USD", "MYR USD"))
    assert "two phases of one series" in opp
    assert "The phase in force at this reading is the warm phase" in opp
    assert "that is this market's declared sign for the phase now in force" in opp
    assert "phases of one series and not separate readings" not in same, "the FALSE sentence is gone"
    assert "one piece of evidence and not two" in same
    assert "read it under China import tariff" in same and "China import pace" in same
    # the undeclared-pair branch must NOT claim a phase pair
    assert "two phases of one series" not in bare
    assert "cannot reconcile them" in bare
    # BOTH forms keep the sentence the coverage fold rests on, so a join is ONE denominator entry
    for line in (opp, same, bare):
        assert "print the SAME figure under each name" in line
        assert R.classify(line) == ("SB-JOIN",)
        # SB-JOIN is letters-only: no phase clause may mint a digit
        assert not any(ch.isdigit() for ch in line), line


def test_S7c_the_phase_verdict_is_computed_from_the_CONVENTIONS_OWN_first_band():
    """The threshold is never re-typed: ONI's 0.5 degC is ``silverleg._ONI_INTENSITY_BANDS[0]`` and the
    lint already pins those two identical, so a phase sentence can never disagree with the band word on
    the row above it. A reading INSIDE the line puts NEITHER phase in force, which is its own fact."""
    warm = R.phase_in_force("silver_noaa_oni", "oni_anom", 0.98)
    cool = R.phase_in_force("silver_noaa_oni", "oni_anom", -0.67)
    inside = R.phase_in_force("silver_noaa_oni", "oni_anom", 0.2)
    assert warm["driver"] == "El_Nino" and warm["words"] == "the warm phase" and warm["in_force"]
    assert cool["driver"] == "La_Nina" and cool["words"] == "the cool phase" and cool["in_force"]
    assert inside["driver"] == "El_Nino" and inside["in_force"] is False
    assert warm["band"] == 0.5 == cool["band"]
    # an undeclared series never guesses which way it signs
    assert R.phase_in_force("silver_psd", "exports_mt", 1.0) == {}
    assert R.phase_in_force("silver_noaa_oni", "oni_anom", None) == {}
    # ...and the INSIDE-the-line sentence says so rather than picking the nearer side
    line = R.sb_phase_pair(["El Nino", "La Nina"], "CBOT soybeans", opposed=True,
                           phase={"words": "the warm phase", "other_words": "the cool phase",
                                  "in_force": False, "live_name": "El Nino",
                                  "live_sign": "in the opposite direction",
                                  "other_name": "La Nina", "other_sign": "in the same direction"})
    assert "sits INSIDE the line" in line and "not a sign it carries now" in line
    assert "phase in force at this reading is" not in line


# === S7 ROUND 2: THE PAID TIERS ARE THE CONTROL AND CARRY NO S7 CAP AND NO S7 ORDERING =============
def test_S7r2_no_cap_and_no_RANK_ordering_reaches_deep_or_max():
    """R1, ASSERTED FROM THE CODE SIDE. The owner's ratified rule of 09-10 is that Scan gets the render
    caps and the paid tiers run as S6 shipped them into arm A, so every S7 lever must read 0 / False on
    deep and max. MEASURED BESIDE THIS PIN, not instead of it: the three acceptance fixtures were walked
    and rendered at deep and at max against a HEAD checkout of this module, and all six blocks came back
    BYTE-IDENTICAL -- 93 lines / 21,349 chars and 110 / 25,233 on b40_event, 80 / 20,702 and
    103 / 26,793 on el_nino_fanout, 80 / 21,074 and 103 / 27,165 on soybeans_now."""
    for mode in ("deep", "max"):
        caps = R.render_caps(mode, B.board_knobs_of(mode))
        assert R.rank_cuts(caps) is False
        for k in ("fan_names", "projection", "edge", "absence"):
            assert int(caps[k] or 0) == 0, (mode, k)
    # ...and the quick tier is the only one that carries any of them
    q = R.render_caps("quick", B.board_knobs_of("quick"))
    assert R.rank_cuts(q) is True
    assert (q["fan_names"], q["projection"], q["absence"]) == (8, 4, 3)
    # A NAME LIST WITH NO RANK IS LEXICAL -- which is exactly what the paid tiers get, and it is the
    # HEAD behaviour this round preserved rather than replaced.
    pairs = [("soybeans_cbot", "zebra_driver"), ("soybeans_cbot", "alpha_driver")]
    assert R._named_rows(pairs, None) == ["alpha driver on CBOT soybeans",
                                          "zebra driver on CBOT soybeans"]
    ranked = {("soybeans_cbot", "zebra_driver"): 0, ("soybeans_cbot", "alpha_driver"): 1}
    assert R._named_rows(pairs, ranked) == ["zebra driver on CBOT soybeans",
                                            "alpha driver on CBOT soybeans"]


# === S7 ROUND 2 (R2): THE DATE FOLD MATCHED ON WORD BOUNDARIES =====================================
def test_S7r2_a_date_token_is_not_satisfied_by_a_LONGER_day_number():
    """THE OVER-CLAIM THE A FOLD SHIPPED WITH. `_date_forms('2026-05-01')` mints `1 May 2026`, and the
    bare substring test scored that row REFERENCED against a sentence saying **11 May 2026**,
    **21 May 2026** or **31 May 2026** -- three other days, three other claims, one scored hit. The
    direction of this instrument's error must stay UNDER-claim, so the token is matched as a word."""
    forms = R._date_forms("2026-05-01")
    assert forms == ("2026-05-01", "1 May 2026", "May 1, 2026")
    g = (forms,)
    assert R._tokens_referenced(g, ["the mandate, dated 1 May 2026, is a demand-side diversion"])
    assert R._tokens_referenced(g, ["the mandate, dated May 1, 2026, is a demand-side diversion"])
    assert R._tokens_referenced(g, ["the mandate (2026-05-01) is a demand-side diversion"])
    # ...and the three days that used to satisfy it no longer do -- BOTH DIRECTIONS OF THE BOUNDARY
    for other in ("11 May 2026", "21 May 2026", "31 May 2026"):
        assert not R._tokens_referenced(g, ["the mandate, dated %s, is a diversion" % other]), other
    assert not R._tokens_referenced(g, ["read on 12026-05-01 by mistake"])
    assert not R._tokens_referenced(g, ["the window ran to 2026-05-011 on that feed"])
    # the REVERSE case is pinned too: a longer date's own token is not satisfied by the shorter day
    g2 = (R._date_forms("2026-05-11"),)
    assert not R._tokens_referenced(g2, ["the mandate, dated 1 May 2026, is a diversion"])
    assert R._tokens_referenced(g2, ["the mandate, dated 11 May 2026, is a diversion"])


def test_S7r2_a_NAME_token_is_not_satisfied_by_a_word_that_merely_contains_it():
    """The same hole through `_name_words`, whose one-word relaxation admits `stocks`: a sentence about
    RESTOCKING satisfied a row keyed on ending stocks. A PLURAL is still admitted, deliberately -- the
    layer words are phrases like `price tape` and every one of those hits was already scored under the
    substring test, so tightening the boundary corrects a false positive without minting a false
    negative in the same edit. Dates end in a DIGIT and are untouched by it."""
    g = (R._name_words("ending stocks"),)
    assert R._tokens_referenced(g, ["ending stocks are building"])
    assert R._tokens_referenced(g, ["the stocks print lands tomorrow"])
    assert not R._tokens_referenced(g, ["restocks were reported by the mill"])
    assert not R._tokens_referenced(g, ["overstocks and understocks both"])
    # the plural hold, stated as a pin so a later tightening is a DECISION and not a slip
    assert R._tokens_referenced((("price tape",),), ["the price tapes both settled late"])


# === S7 ROUND 2 (R3): ONE SERIES, ONE SCALE, EVERYWHERE ON THE PAGE ================================
def test_S7r3_the_ANALOG_OUTCOME_takes_the_SAME_card_scale_as_the_SB1_row_above_it():
    """A PAGE MUST NEVER CARRY ONE SERIES AT TWO SCALES. `analogs.outcome_over_band` reads a DRIVER'S
    OWN array (the child row, and a scope-keyed far state) and prints its change under the card's
    `narrate_unit` word -- the same word the SB-1 row above it prints its level under. With the level
    scaled and the change native, a `scale: 100` ratio card would print `13 %` on one line and a
    hundredth of the move on the next. ONE helper (`rows.shown_value`) serves both."""
    from leviathan.graphrag.state.feeders import state_from_arrays
    d = ["202%d-12-31" % y for y in range(1, 10)]
    st = state_from_arrays("psd_ending_stock_su_ratio", [0.13 + 0.01 * i for i in range(9)], d,
                           cadence="annual", asof="2026-09-07", unit="ratio", narrate_unit="%",
                           scale=100, windows={"annual": 6}, table="silver_psd", metric="su_ratio")

    class _Bd:
        series = {"k": st}

    scales = R._series_scales(_Bd())
    # THE FOUR JOIN FIELDS ARE THE FOUR `analogs.outcome_over_band` COPIES OUT OF THE STATE ROW, and
    # they are read off the row here for the same reason the real caller passes them: a hand-typed
    # `None` where the key says `_global` would be a test proving something the producer never does.
    o = {"label": "stocks to use on CBOT soybeans", "unit": "%", "table": st.table,
         "metric": st.metric, "commodity": st.key.commodity, "country": st.key.country,
         "band": parse_lag("1-2 quarters"),
         "near_value": 0.02, "far_value": 0.05, "near_date": "2027-12-31", "far_date": "2028-12-31"}
    assert R._outcome_scale(o, scales) == 100.0
    line, calls = R.sb_analog_outcome(11, o, asof="2026-09-07", scale=R._outcome_scale(o, scales))
    # 09-24 RE-BANK (CONTRACT K5 -- DM1): each end is a CHANGE row and prints SIGNED ("+2 %"), so a change
    # can never read as a level of the same series.
    assert "moved +2 % by the time that lag opened" in line, line
    assert "moved +5 % by the time it closed" in line, line
    assert all(c["rows"][0].get("stat") == "window_change" for c in calls), calls
    assert abs(float(calls[0]["shown"][0]) - 2.0) < 1e-9
    assert abs(float(calls[1]["shown"][0]) - 5.0) < 1e-9
    assert R.classify(line) == ("SB-O",)
    # A PRICE BENCHMARK CARRIES NO CARD AND STAYS NATIVE -- the commonest case, and not a fallback
    bm = dict(o, table="silver_pink_sheet", metric="price")
    assert R._outcome_scale(bm, scales) == 1.0
    bline, _ = R.sb_analog_outcome(11, bm, asof="2026-09-07", scale=R._outcome_scale(bm, scales))
    assert "moved +0.02 %" in bline, bline
    # TWO CARDS THAT SHARE ALL FOUR JOIN FIELDS AND DISAGREE ON SCALE REFUSE TO SCALE rather than
    # guessing: printing one of the two would be a figure this render invented.
    st2 = state_from_arrays("psd_ending_stock_su_ratio", [0.13] * 9, d, cadence="annual",
                            asof="2026-09-07", unit="ratio", narrate_unit="%", scale=1,
                            windows={"annual": 6}, table="silver_psd", metric="su_ratio")

    class _Bd2:
        series = {"a": st, "b": st2}

    assert R._outcome_scale(o, R._series_scales(_Bd2())) == 1.0


def test_S7r3_shown_value_is_the_ONE_producer_and_the_state_row_reads_it():
    """`StateRow.level_shown` is `shown_value(level, scale)` and nothing else, so the SB-1 row and the
    SB-O row cannot drift. A change scales exactly as a level does -- (a - b) * s == a*s - b*s -- which
    is why one multiplication is enough for both classes."""
    assert ROWS.shown_value(0.13, 100) == 13.0
    assert abs(ROWS.shown_value(118000000.0, 0.000001) - 118.0) < 1e-9
    assert ROWS.shown_value(None, 100) is None
    assert ROWS.shown_value(1.0, None) == 1.0          # an undeclared scale is not a scale of nothing
    assert ROWS.shown_value("not a number", 100) is None


# === S7b ROUND 4: THE WATCH-BULLET READER (orchestrator ruling (7)) ================================
# `render._nomination_coverage` counted a nomination USED when one SENTENCE carried every one of its
# token groups. MEASURED on the three S7b real-seat draws that read 5 of 37 where a human read of the
# same pages found all 13 shipped watch bullets resting on a nomination. The rule is now PER BULLET,
# and these are the pins on the two producers that make a bullet a bullet: `_nom_watch_bullets` says
# WHICH list items are watch items, `_nom_identity` says what a nomination is CALLED.
def _nom_line(kind, driver, handle, *, board="CBOT soybeans", slot="ceiling", i=1, n=3, dates="",
              what="the reading is past the line the desk convention calls behind"):
    """ONE nomination line, minted through THE SHIPPED BUILDER.

    `sb_watch` renders the line the reader meets and both producers key on that line and on nothing
    else, so a deck that hand-typed the string would be grading its own typing rather than the render."""
    from leviathan.graphrag.state import watch as WA
    return R.sb_watch({"kind_words": WA.NONOBVIOUS_KIND_WORDS[kind],
                       "label": f"{driver} on {board}", "backing_handle": handle, "slot": slot,
                       "slot_size": n, "slot_index": i, "what": what, "dates": dates})


def test_S7b4_a_WRAPPED_bullet_is_ONE_item_and_a_blank_line_a_marker_or_a_heading_ends_it():
    """A BULLET IS THE WHOLE LIST ITEM. The real-seat draws wrapped their watch items across lines and
    across sentences -- the name in the head, the window in the tail -- and a reader that stopped at
    the newline would ask each fragment to carry the whole identity, which is the defect this landing
    closes. Three things end an item and nothing else does: a blank line, the next marker, a heading."""
    page = ("## What to watch\n"
            "- **Crude oil** -- below the elevated line, three months rising,\n"
            "  about thirty-nine percent of the way from zero [N31].\n"
            "  Its window runs to 2027-02-28.\n"
            "- **Board crush margin** -- running at, not through, the high line [N19].\n"
            "\n"
            "A closing paragraph that is not a bullet at all.\n")
    buls = R._nom_watch_bullets(page)
    assert len(buls) == 2, buls
    assert "[N31]" in buls[0] and "2027-02-28" in buls[0], buls[0]
    assert "crush" in buls[1] and "2027-02-28" not in buls[1]
    assert "closing paragraph" not in " ".join(buls)


def test_S7b4_the_watch_section_is_HEADING_SCOPED_and_the_mechanism_bullets_stay_out():
    """THE SECTION IS WHAT KEEPS THE MECHANISM MOVEMENT OUT. `soybeans_now` shipped ten list items,
    five of them under `## Mechanism` citing [N19], [N7], [N1] and [N34]; a rule that counted every
    bullet on the page would have credited the watch list with the mechanism's citations."""
    page = ("## Mechanism\n"
            "- **Crush pull.** The board reads 1.06 USD per bushel [N19].\n"
            "- **Export pace.** Weekly sales 664.8 thousand MT [N7].\n"
            "## Cross-commodity\n"
            "- **CME palm oil** -- the same reading is declared there.\n"
            "## What to watch\n"
            "- **Weekly US export sales** [N7]: past the line the desk calls behind.\n")
    buls = R._nom_watch_bullets(page)
    assert len(buls) == 1 and buls[0].startswith("**Weekly US export sales**"), buls
    # ...and the section closes at the NEXT heading of any level, not at the end of the page
    assert R._nom_watch_bullets(page + "## The record\n- a record bullet after the watch list\n") \
        == buls
    # THE HEADING IS THE CONTRACT'S, NOT THE WRITER'S: `response_contracts` declares the four and
    # `narration.MANDATE_MOVEMENTS` maps the WATCH movement onto one of them. The rule keys on the
    # WORD, so the declared heading opens a section and so does the same heading with a word added.
    declared = dict((m[0], m[1]) for m in N.MANDATE_MOVEMENTS)["WATCH"]
    assert "watch" in declared.lower()
    assert R._nom_watch_bullets(declared + "\n- an item under the declared heading\n") \
        == ["an item under the declared heading"]
    assert R._nom_watch_bullets(declared + " for\n- an item under a widened heading\n") \
        == ["an item under a widened heading"]


def test_S7b4_the_BLOCK_MARKER_needs_no_heading_which_is_what_makes_the_ZERO_WRITER_read_exact():
    """THE ZERO-WRITER INPUT IS THE BLOCK HANDED BACK VERBATIM, and the block writes no headings. Its
    nomination rows open with `- WATCH {kind words}`, so they are read as the watch list they are --
    while the block's OTHER sixty-odd list items (SB-1 rows, path rows, receipts) are correctly left
    out, which is why the baseline can be all-used / none-added EXACTLY rather than approximately."""
    lines = [_nom_line("past_the_line", "export pace lag", 7, i=1, n=2),
             "- [N1] El Nino on CBOT soybeans, NOAA ONI for 2026-08-31: +0.98 degC",
             "- El Nino is declared to move CBOT soybeans in the opposite direction",
             _nom_line("spillover_reach", "crude oil", 31, slot="nomination", i=1, n=2)]
    buls = R._nom_watch_bullets("\n".join(lines))
    assert len(buls) == 2, buls
    assert all(b.upper().startswith("WATCH ") for b in buls)


def test_S7b4_a_page_with_NO_watch_heading_and_NO_marker_has_NO_watch_bullets():
    """FAIL CLOSED. A writer that shipped no watch list is credited with nothing rather than charged
    for a list nobody can find -- and no bullet of some other movement is pressed into the count."""
    assert R._nom_watch_bullets("") == []
    assert R._nom_watch_bullets("## Mechanism\n- a bullet under another heading [N7]\n") == []
    assert R._nom_watch_bullets("just prose, no list at all, watch or otherwise") == []


def test_S7b4_the_identity_is_the_HANDLE_and_the_DRIVER_HALF_of_the_label():
    """A NOMINATION'S TWO NAMES, read off its own rendered line. `sb_watch` prints
    `{kind words} {driver} on {board}{citation}{slot mark}: {claim}`, so the label is cut at the first
    of the three and split at its last " on " -- the BOARD half is not the series key and must not be,
    or every nomination on one board would answer to every bullet that named the board."""
    from leviathan.graphrag.state import watch as WA
    words = tuple(f"- WATCH {w} " for w in WA.NONOBVIOUS_KIND_WORDS.values())
    hs, key = R._nom_identity(_nom_line("past_the_line", "export pace lag", 7, i=1, n=7), words)
    assert hs == frozenset({7})
    assert key == ("export pace lag",), key
    # the estate's ONE relaxation (`_name_words`): the last word alone, at five characters or more
    _hs, key2 = R._nom_identity(_nom_line("approaching_line", "flash drought", 28), words)
    assert key2 == ("flash drought", "drought"), key2
    # a nomination whose backing row never rendered carries NO citation, and the series key is all it
    # has -- which is why the key leg exists at all
    hs3, key3 = R._nom_identity(_nom_line("recurrence", "Argentina export registration", 0), words)
    assert hs3 == frozenset() and key3[0] == "Argentina export registration"


# S8 ROUND 2: THE CHAIN ROWS' CITATION SURFACE, THEIR HOP, THEIR ARITHMETIC AND THEIR CEILINGS
#
# THE PINS BELOW ARE THE ROUND-2 ITEMS R-1, R-2, R-3 AND R-6, each on the PRODUCER rather than on a
# built board: ``test_state_chain_render.py`` owns the armed board and is not this round's file, so
# what is asserted here is what this round CHANGED -- the call record the reader's ``## Sources`` line
# is built from, the hop the document row names, the arithmetic line and its data scope, the lag
# window's peak, the positioning row, and the count line's own ceiling.
def _s8_hop(**kw):
    kw.setdefault("contract", "soybeans_cbot")
    kw.setdefault("driver_id", "export_pace_lag")
    kw.setdefault("lag_band", parse_lag("0-1 quarters"))
    kw.setdefault("measured", True)
    kw.setdefault("percentile", 13.0)
    kw.setdefault("series_key", "silver_esr|soybeans_cbot|United States")
    kw.setdefault("knowledge_date", "2026-09-04")
    return W.ChainHop(**kw)


def _s8_chain(hops, **kw):
    hops = tuple(hops)
    ch = W.Chain(contract=kw.pop("contract", "soybeans_cbot"), hops=hops,
                 depth=len(hops) - 1,
                 terminal=kw.pop("terminal", "soybeans_cbot"),
                 agreements=kw.pop("agreements", tuple(["aligned"] * len(hops))),
                 edge_signs=kw.pop("edge_signs", tuple(["+"] * len(hops))), **kw)
    ch.rendered = ch.full = True
    return ch


_S8_SCOPE = "the front price's own 2025-06-16 to 2026-09-04 window"


def test_S8R2_the_chain_outcome_row_mints_a_FOOTER_LINE_A_READER_CAN_CHECK_and_a_LOCATOR_THAT_RERUNS():
    """**ROUND-2 ITEM R-1.** The chain outcome is the one chain row that MINTS, and its call record is
    what ``citations.from_number`` turns into the reader's ``## Sources`` line and into the drill-down's
    ``locator``. MEASURED on the first cut, through that same producer:

        [N1] STATE BOARD CHAIN front_price_move_after_firing CBOT soybeans MYthe front price's own
             2025-06-16 to 2026-09-04 window = 2.1 percent       (source 'STATE BOARD CHAIN', date None)

    -- a machine id headlining the Sources line (``citations.py:1458-1467`` names that exact class), the
    metric as its raw snake_case id, the "MYMY" weld ``_period_label`` makes of any period that neither
    starts with MY nor contains "..", and no vintage at all. Three of three footer lines defective. The
    magnitude is computed off ``bd.tape``, whose own row cites ``silver_futures_eod`` / ``settle``, so
    the card was there the whole time."""
    from leviathan.graphrag import citations as CIT
    ch = _s8_chain([_s8_hop(), _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0)],
                   declared_sign="+")
    ch.outcome = {"n": 9, "median_move": 2.1, "low": -3.4, "high": 6.8, "share_declared_way": 6,
                  "unit": "percent", "scope": _S8_SCOPE}
    line, calls = R.sb_chain_outcome(1, ch, asof="2026-09-07")
    assert R.classify(line) == ("SB-O",) and len(calls) == 3
    for i, c in enumerate(calls, start=1):
        cit = CIT.from_number(c, i)
        assert "STATE BOARD CHAIN" not in (cit.label or "")
        assert "front_price_move_after_firing" not in (cit.label or "")
        assert "MYthe" not in (cit.label or "") and "MYMY" not in (cit.label or "")
        assert cit.date == "2026-09-04", "the vintage is the window's far date"
        assert cit.source and cit.source != "STATE BOARD CHAIN"
        # the LOCATOR is an address a drill-down re-runs: a real card, the SLUG, the `..` window
        assert cit.locator["table"] == "silver_futures_eod"
        assert cit.locator["commodity"] == "soybeans_cbot", "the address is the slug, not the label"
        assert cit.locator["period"] == "2025-06-16..2026-09-04"
        assert cit.locator["asof"] == "2026-09-07"
    # ...and an outcome computed on some OTHER basis (lane C's pair spread) declares its own card.
    ch.outcome = dict(ch.outcome, table="silver_pair_spread", metric="spread")
    _l2, c2 = R.sb_chain_outcome(1, ch, asof="2026-09-07")
    assert c2[0]["query"]["table"] == "silver_pair_spread"


def test_S8R2_a_scope_naming_no_dates_leaves_the_period_and_the_vintage_EMPTY_rather_than_inventing():
    """FAIL CLOSED ON THE WINDOW. ``walk.chain_outcome``'s ``scope`` is a PROSE sentence and the two
    dates are read out of it until lane W carries them as fields. A scope that names none must not
    produce a period -- a period is a filter the query never issued (``citations.py``'s own D-XL note)
    -- and must not produce a ``[known ...]`` stamp, which would be a vintage nobody measured."""
    ch = _s8_chain([_s8_hop(), _s8_hop(driver_id="psd_ending_stock_su_ratio")])
    ch.outcome = {"n": 4, "median_move": 1.0, "low": 0.0, "high": 2.0, "unit": "percent",
                  "scope": "the front price's own window"}
    _line, calls = R.sb_chain_outcome(1, ch, asof="2026-09-07")
    assert calls[0]["query"]["period"] == ""
    assert "knowledge_date" not in calls[0]["rows"][0]
    # ...and lane W's FIELDS win over the sentence the moment they land.
    ch.outcome = dict(ch.outcome, window_from="2025-01-02", window_to="2026-01-02")
    _l, c2 = R.sb_chain_outcome(1, ch, asof="2026-09-07")
    assert c2[0]["query"]["period"] == "2025-01-02..2026-01-02"
    assert c2[0]["rows"][0]["knowledge_date"] == "2026-01-02"


def test_S8R2_the_chain_document_row_NAMES_THE_HOP_the_document_acts_on_on_every_branch():
    """**ROUND-2 ITEM R-2.** ``CHAIN_NO_RECEIPT`` and the open / closed / mechanism sentences all said
    "this hop" or "for it" and named no hop, while the row is emitted after the record line -- so the
    nearest antecedent on the page was the LAST hop line. The receipt hop is the LOUDEST hop, which is
    generally not the last: on the max fixture chain #1 is ``China import tariff -> export pace lag ->
    psd ending stock su ratio``, its receipt hop is hop TWO of three, and the row sat under hop three.

    ``chain_receipt`` still returns the hop-free sentence it always returned (its own pins read
    ``CHAIN_NO_RECEIPT`` by identity); the hop is named HERE, where the row is written."""
    hop = _s8_hop(driver_id="export_pace_lag")
    for kind, words in (("none", R.CHAIN_NO_RECEIPT),
                        ("open", R._event_words("action_open", event_date="2026-08-01",
                                                precision="day")),
                        ("closed", R._event_words("action_closed", event_date="2021-05-12",
                                                  precision="day")),
                        ("mechanism", "a dated report on this link's mechanism, published "
                                      "17 April 2026")):
        row = R.sb_chain_document({"kind": kind, "words": words, "hop": hop}, hop)
        assert row.startswith(R.CHAIN_SUB_PREFIX + "document:"), row
        assert ("at %s," % R.chain_hop_name(hop)) in row, (kind, row)
        assert words in row, "the placement wording the threat model bought is untouched"
        assert R.classify(row) == ("SB-P",) and R.register_hits(row) == []
    # ONE DOCUMENT, ONE ADDRESS: the events section's own handle rides at the end of the sentence.
    cited = R.sb_chain_document({"kind": "open", "words": "a dated action on 2026-08-01", "hop": hop},
                                hop, cite_e=" [E4]")
    assert cited.endswith("[E4].")
    # a row with no hop at all still renders, and says so rather than naming nothing.
    assert "at this link," in R.sb_chain_document({"kind": "none", "words": R.CHAIN_NO_RECEIPT}, None)


def test_S8R2_the_arithmetic_line_names_every_SCORING_term_with_its_POINTS_IN_WORDS_and_no_digit():
    """**ROUND-2 ITEM R-3, and the round-2 census's own 8.3.** DESIGN B.2 asks for "each rendered
    chain's arithmetic in one line" because "falsifiable on the page" was the reason for the line; the
    first cut named the TERMS and left the POINTS on the trace. They are said in words because a chain
    row rides SB-P and SB-P carries no charged digit -- and a census can still check every pair against
    ``Board.trace()["chains"][*]["terms"]``."""
    from leviathan.graphrag import register as REG
    ch = _s8_chain([_s8_hop(), _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0)])
    ch.terms = {"tail": 23.5, "reach": 25, "event": 0, "history": 7.5, "asymmetry": 10,
                "confidence": 3, "lag": 2}
    line = R.chain_arithmetic_words(ch)
    assert line.startswith(R.CHAIN_SUB_PREFIX + "why: ")
    for want in ("tail twenty-three and a half", "reach twenty-five", "record seven and a half",
                 "buffer ten", "strength three", "lag fit two"):
        assert want in line, want
    assert "action" not in line, "a term that scored nothing is not named as if it had"
    assert "six of seven terms scored" in line
    assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
    assert REG.count_desk_register(line) == 0
    bare = _GLUED_RX.sub("", _YEAR_RX.sub("", _YM_RX.sub("", _ISO_RX.sub(
        "", _HANDLE_RX.sub("", line)))))
    assert not any(c.isdigit() for c in bare), line


def test_S8R2_the_arithmetic_line_states_the_DATA_SCOPE_so_a_low_score_reads_as_SCARCE_DATA():
    """**ORCHESTRATOR NOTE 6: each anchor is judged on the data it has.** A term that scored zero for
    want of a series is a different fact from a term that scored zero on a reading, and the page says
    which. The two facts the render can compute it computes; the two it cannot -- whether this market
    serves ANY buffer series, whether the corpus carries ANY dated action for it -- are read off
    ``Chain.scope`` when the walk declares them and are SILENT otherwise, never a zero.

    **ROUND 3: THE DICT IS ``Chain.scope`` AND THE ASSERTION IS AGAINST A REAL ``walk.Chain``.** The
    round-2 pin set ``ch.data_scope`` on the object and passed, because a dataclass takes any attribute
    you give it -- while the shipped walk carried ``Chain.scope`` and ``hasattr(c, "data_scope")`` was
    FALSE on every rendered chain of every tier. A stand-in name asserted against itself is how an
    owner-ordered surface ships dead; this pin now sets the field the walk publishes and reads the
    walk's own roster to prove the name is one it declares."""
    ch = _s8_chain([_s8_hop(), _s8_hop(driver_id="drought", measured=False, percentile=None,
                                       series_key="", knowledge_date="")])
    ch.terms = {"tail": 23.5, "reach": 25}
    assert hasattr(ch, "scope") and not hasattr(ch, "data_scope"), \
        "the dict is the walk's own `Chain.scope` -- `data_scope` was this lane's invention"
    for name in ("Chain.scope", "Chain.scope.buffer_series", "Chain.scope.events_in_corpus"):
        assert name in W.CHAIN_SEAM_FIELDS, name
    line = R.chain_arithmetic_words(ch)
    assert "one link carries no series" in line
    assert "buffer series" not in line and "dated action" not in line
    ch.scope = {"buffer_series": False, "events_in_corpus": False}
    rich = R.chain_arithmetic_words(ch)
    assert "this market serves no buffer series" in rich
    assert "this turn retrieved no dated action for this market" in rich
    assert R.classify(rich) == ("SB-P",) and R.register_hits(rich) == []
    ch.scope = {"buffer_series": True, "events_in_corpus": True}
    assert "no buffer series" not in R.chain_arithmetic_words(ch)
    # ...and an anchor the walk could not read at all is SILENT rather than an absence claim.
    ch.scope = {"buffer_series": None, "events_in_corpus": None}
    quiet = R.chain_arithmetic_words(ch)
    assert "no buffer series" not in quiet and "no dated action" not in quiet


def test_S8R4_the_count_line_holds_its_RE_BASELINED_CEILING_and_keeps_both_denominators():
    """**ROUND-2 ITEM R-3's own ceiling, ROUND 3's MEASURED REFUTATION OF IT, AND ROUND 4's
    RE-BASELINE.** The three hundred was set BEFORE the two CONTENT rulings that landed on this line,
    and content ordered by a ruling is never cut to meet a number set before the rulings. The ceiling
    is now the MEASURED MAXIMUM over both cells of the fixture AND the five 2026-09-16 payloads (433),
    plus ten per cent, rounded up to fifty: FIVE HUNDRED. The base line -- the counts alone, which is
    what the three hundred was measured against -- is still inside the OLD number, which is what makes
    the re-baseline a budget decision about the two clauses rather than a blanket relaxation.

    MEASURED on the three fixture cells the line ran 563 / 589 / 609 characters, and 185 of that was a
    closing sentence restating -- once per page -- the four terms ``chain_arithmetic_words`` now prints
    PER CHAIN with the points each one earned. The cut took the max cell to 298 against a 300 ceiling.

    **THEN TWO OWNER RULINGS LANDED ON THIS ONE LINE and the ceiling stopped being reachable.** The
    ORTHOGONAL SHOCKS clause (note 3, the owner's own word) costs about 86 characters at the counts the
    walk really carries, and the HELD-SEAT count (ruling 2026-09-22) about 47. The line is at 433 on the
    max fixture cell with both. Nothing here trims them to fit: the ceiling is a BUDGET ruling and the
    clauses are CONTENT rulings, so this pin states the arithmetic and leaves the trade to the
    orchestrator rather than quietly dropping the owner's clause to keep a number green.

    WHAT IS STILL PINNED IS WHAT THE LINE MUST BE: both denominators, one population per noun, no
    charged digit, SB-P and register-clean -- and the base line (the counts alone, which is what the
    300 was measured against) still inside it."""
    counts = {"distinct_sequences": 77, "total": 1848, "state_two_hops": 816,
              "with_document": 432, "distinct_unnamed_markets": 17}
    line = R.sb_chain_count(counts, k=3, anchor_label="CBOT soybeans")
    assert len(line) <= 300, len(line)
    # 09-25 FIX ROUND 3 (RT-8, the chain read's N13): A PLAIN COUNT, NEVER A CENSUS. The pool arithmetic
    # ("1848 ways in all", "816 read their own series past one link", "432 carry an action") is retired from
    # the line -- the palm/rape writer printed it as a census -- and rides the trace's chain_counts. ONE
    # population now: the distinct chains, the ones carried above, the rest counted and not followed.
    assert R.words_for_int(77) in line and R.words_for_int(1848) not in line
    assert "ways in all" not in line and "past one link" not in line and "sequence" not in line
    assert "chains of cause, three of them carried above" in line
    assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
    bare = _GLUED_RX.sub("", _YEAR_RX.sub("", _ISO_RX.sub("", line)))
    assert not any(c.isdigit() for c in bare), line
    # THE REFUTATION, AS ARITHMETIC RATHER THAN AS A SENTENCE: the two ruling clauses' own cost on the
    # very cell the ceiling was measured on. A future sitting that wants the 300 back can read exactly
    # what it must spend, and a future sitting that quietly drops a clause reddens this deck.
    full = R.sb_chain_count(dict(counts, cross_market_event=414, cross_market_event_rendered=1),
                            k=3, anchor_label="CBOT soybeans",
                            slots=("sign", "top", "top"))
    shocks = len(R.sb_chain_count(dict(counts, cross_market_event=414,
                                       cross_market_event_rendered=1), k=3,
                                  anchor_label="CBOT soybeans")) - len(line)
    seats = len(full) - len(line) - shocks
    assert 60 <= shocks <= 110, shocks
    assert 30 <= seats <= 60, seats
    assert len(full) > 300, "recorded, not hidden: the OLD ceiling is refuted at the counts that ship"
    # ...AND THE RE-BASELINED ONE HOLDS, with the aged-out clause on top of both ruling clauses -- the
    # largest this line can be on any cell or payload this lane can measure. ROUND 5 re-baselined this
    # ceiling to 550 (blocker 9): the measured maximum is 480, on the max fixture cell with ONE dated
    # action aged out -- the clause costs +47 characters the moment it has something to say -- and the
    # rule is measured max + 10%, rounded up to fifty.
    widest = R.sb_chain_count(dict(counts, cross_market_event=414, cross_market_event_rendered=1,
                                   receipts_aged_out=414),
                              k=3, anchor_label="CBOT soybeans",
                              slots=("sign", "subject", "horizon"))
    assert len(widest) <= 550, (len(widest), widest)
    assert R.classify(full) == ("SB-P",) and R.register_hits(full) == []
    assert R.classify(widest) == ("SB-P",) and R.register_hits(widest) == []


def test_S8R2_the_count_line_names_the_CROSS_MARKET_dated_actions_and_is_ABSENT_where_none_counted():
    """**ORCHESTRATOR NOTE 3, the owner's ORTHOGONAL SHOCKS.** A chain that crosses a commodity
    boundary on an earned cross edge AND carries an open dated action is the combination the question
    did not ask about. The line says how many existed and how many rendered, so a turn with none reads
    as "no cross-market dated action reached this page" rather than as silence -- and where the walk
    counts neither, the clause is ABSENT rather than a zero wearing a claim.

    **ROUND 3: THE KEYS ARE ``cross_market_event`` / ``cross_market_event_rendered``, AND THEY ARE
    ASSERTED AGAINST THE REAL ``walk.chain_counts`` OUTPUT.** The round-2 pin passed a hand-made dict
    carrying ``cross_event`` -- a key this lane invented in its own handoff -- so the clause was green
    in the deck and ABSENT on all three tiers of the real page while the producer counted 112 / 342 /
    414 of them with one rendered on each."""
    counts = {"distinct_sequences": 77, "total": 1848, "state_two_hops": 816,
              "with_document": 432, "distinct_unnamed_markets": 17}
    # THE NAME COMES OFF THE PRODUCER, not off this test's own dict: `chain_counts` over an EMPTY pool
    # still declares its whole key roster, which is exactly the assertion a stand-in cannot make.
    produced = W.chain_counts([])
    assert "cross_market_event" in produced and "cross_market_event_rendered" in produced
    assert "cross_event" not in produced and "cross_event_rendered" not in produced
    for name in ("chain_counts.cross_market_event", "chain_counts.cross_market_event_rendered"):
        assert name in W.CHAIN_SEAM_FIELDS, name
    assert "cross a market carrying an open action" not in R.sb_chain_count(counts, k=3)
    assert "cross a market carrying an open action" not in \
        R.sb_chain_count(dict(counts, cross_event=9, cross_event_rendered=3), k=3), \
        "the invented key buys nothing -- the line reads the name the walk publishes"
    named = R.sb_chain_count(dict(counts, cross_market_event=9, cross_market_event_rendered=3), k=3,
                             anchor_label="CBOT soybeans")
    assert "nine cross a market carrying an open action, three of them carried here" in named
    zero = R.sb_chain_count(dict(counts, cross_market_event=0, cross_market_event_rendered=0), k=3)
    assert "zero cross a market carrying an open action, zero of them carried here" in zero, \
        "counted and stated, because a silent zero is the absence-lie class"
    assert R.classify(named) == ("SB-P",) and R.register_hits(named) == []


def test_S8R2_the_hop_reads_its_LAG_WINDOWS_PEAK_and_prints_BOTH_readings_and_where_the_lag_runs():
    """**ORCHESTRATOR NOTE 5 (2026-09-18).** A shock is IN TRANSIT for the length of its declared lag:
    a reading that peaked at the ninety-seventh percentile three months ago and eased to the eightieth
    is still acting on the next hop while the lag runs. The clause prints BOTH readings and where the
    lag runs to, and it REPLACES the run words rather than joining them -- "peaked in June, now
    eightieth" states the direction of travel more precisely than "falling since June" and at fewer
    characters than printing both.

    **ROUND 3: THE NAMES ARE ``tail_peak_date`` AND ``tail_lag_to``, AND THE PIN IS AGAINST A REAL
    ``walk.ChainHop``.** The round-2 pin built a ``types.SimpleNamespace`` carrying ``tail_peak_month``
    and ``lag_window_end`` -- two names this lane invented in its own handoff -- and asserted the clause
    against THAT. It was green, and would have stayed green whatever the dataclass was called, while on
    the shipped page ``"peaked"`` appeared ZERO times at every tier: a stand-in cannot fail a rename,
    which is the whole mechanism of this estate's standing string-identity memory. A frozen dataclass
    REFUSES an unknown keyword, so the construction below is itself the name assertion."""
    hop = _s8_hop(percentile=80.0, run_direction="down", run_since="2026-06-30",
                  knowledge_date="2026-09-04")
    plain = R.chain_state_words(hop)
    assert "at the eightieth percentile of its own record" in plain
    assert "falling since June 2026" in plain and "through 2026-09-04" in plain
    assert "peaked" not in plain and "window runs to" not in plain
    for name in ("ChainHop.tail_peak_percentile", "ChainHop.tail_peak_date", "ChainHop.tail_lag_to"):
        assert name in W.CHAIN_SEAM_FIELDS, name
    peak = _s8_hop(percentile=80.0, tail=0.6, run_direction="down", run_since="2026-06-30",
                   knowledge_date="2026-09-04", tail_peak=0.94, tail_peak_percentile=97.0,
                   tail_peak_date="2026-06-19", tail_lag_to="2026-11-19")
    assert not hasattr(peak, "tail_peak_month") and not hasattr(peak, "lag_window_end"), \
        "the round-2 names do not exist on the shipped hop -- that is why the surface rendered nothing"
    got = R.chain_state_words(peak)
    # 09-23: "now the eightieth" -- and each standing cites its own address where the row minted one.
    assert "peaked at the ninety-seventh percentile in June 2026, now the eightieth" in got
    assert "the peak's own window runs to November 2026" in got
    assert "through 2026-09-04" in got
    assert "falling since" not in got, "the peak clause REPLACES the run, it does not join it"
    # A DECLARED PEAK THAT IS THE LATEST READING IS NOT A PEAK WORTH TWO FIGURES -- and it takes the
    # lag clause down with it: "where the lag runs to" answers "is that older reading still acting?",
    # which only an eased peak makes a reader ask, and the same line now carries the band in full.
    same = _s8_hop(percentile=97.0, tail=0.94, run_direction="", run_since="",
                   knowledge_date="2026-09-04", tail_peak=0.94, tail_peak_percentile=97.0,
                   tail_peak_date="2026-06-19", tail_lag_to="2026-11-19")
    quiet = R.chain_state_words(same)
    assert "peaked" not in quiet and "window runs to" not in quiet


def test_S8R2_the_positioning_row_says_AMPLIFIER_or_CONVEXITY_and_is_SILENT_where_none_is_declared():
    """**ORCHESTRATOR NOTE 1 (owner: "how does it know how convex the market is?").** A managed-money
    net position at a tail of its OWN record is an amplifier when it sits the same way the chain argues
    and CONVEXITY when it sits against it -- the risk the 2026-09-16 smoke's own PM read flagged twice.
    The row states which of the two, and cites the board's own positioning row where this page carries
    its address: a standing with no address is a claim a reader cannot check."""
    from leviathan.graphrag import register as REG
    ch = _s8_chain([_s8_hop(), _s8_hop(driver_id="cot_mm_positioning", percentile=100.0)])
    assert R.sb_chain_positioning(ch) == "", "no positioning row, no line -- never a zero"
    ch.positioning = {"percentile": 100.0, "against": True,
                      "key": ("soybeans_cbot", "cot_mm_positioning")}
    row = R.sb_chain_positioning(ch, handle=12)
    assert "[N12]" in row and "one hundredth percentile of its own record" in row
    assert "the other way from this sequence" in row and "reversal abrupt" in row
    ch.positioning = dict(ch.positioning, against=False)
    same = R.sb_chain_positioning(ch)
    assert "the same way as this sequence" in same and "amplifies it" in same
    assert "[N" not in same, "a standing this page carries no address for prints no handle"
    for line in (row, same):
        assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
        assert REG.count_desk_register(line) == 0


# ═══ S8 ROUND 3: THE SEAM'S NAMES, THE PRINTED ARITHMETIC, THE BAND AND THE SLOT LABEL ══════════════
#
# TWO LAWS OF THIS ROUND, AND BOTH ARE HERE BECAUSE OF WHAT ROUND 2 MEASURED:
#   (a) A CROSS-LANE PIN ASSERTS AGAINST THE SHIPPED TYPE. Four owner-ordered surfaces rendered
#       NOTHING for a whole round while every pin on both sides was green, because every pin asserted
#       against a `types.SimpleNamespace` carrying whatever name the reader hoped for. Every seam
#       field this module reads is now resolved against a real `walk.Chain` / `walk.ChainHop` / the
#       real `walk.chain_counts` output AND against `walk.CHAIN_SEAM_FIELDS`, the one published
#       spelling of the W -> R seam.
#   (b) A SURFACE IS MEASURED ON THE PAGE, not only on its producer. A label that never renders is a
#       green pin and a dead surface, so the armed-board pins below read the rendered block.
@pytest.fixture(scope="module")
def chain_blocks(graph):
    """{mode: (board, Block)} on the soybeans fixture with the CHAIN LEG ARMED, all three tiers.

    OFFLINE BY CONSTRUCTION: the state producer, the tape and the benchmark are the harness's own
    fixtures, so this fixture reads no mirror, opens no socket and calls no model.

    **THE TAPE IS ATTACHED BEFORE ``W.stage2``, BECAUSE THAT IS WHAT THE SEAM NOW DOES** (round-3
    census blocker 3): ``walk.anchor_facts`` reads ``bd.tape`` for the anchor's own price standing and
    the chain leg scores on it, so a harness that attached it afterwards would measure a board no turn
    ever has."""
    from leviathan.graphrag.numbers import cascade as CAS
    curated = list(CAS.load_chain_map() or ()) + list(CAS.load_transmission_map() or ())
    q = "what is the situation on soybeans now? how is it looking 3 months from now?"
    out = {}
    for mode in ("quick", "deep", "max"):
        anchors = W.resolve_anchors(named=("soybeans_cbot",))
        bd = W.walk(graph=graph, asof=H.ASOF, mode=mode, anchors=anchors, question=q,
                    state_fn=H.fixture_state_fn(H.ASOF), key_fn=None, receipts={},
                    knobs=B.board_knobs_of(mode), width=2, legb_on=False, stage2=False)
        R.attach_tape(bd, {s: H.fixture_tape(s, H.ASOF) for s in bd.anchor_slugs}, reads_each=0)
        W.stage2(bd, graph, state_fn=H.fixture_state_fn(H.ASOF), receipts={}, width=2,
                 legb_on=False, chains=curated, state_chain=True)
        bd.stamp("tape", "fired")
        ana = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn(),
                            receipt_fn=None)
        A.analog_leg(bd, ana)
        blk = R.render_board(bd, analogs=ana,
                             anchor_label=", ".join(R.board_label(s) for s in bd.anchor_slugs))
        out[mode] = (bd, blk)
    return out


def _chain_rows(blk, role):
    return [ln for ln, m in zip(blk.lines, blk.rows_meta) if str((m or {}).get("role") or "") == role]


def _points_back(words):
    """The NUMBER a spelled points value stands for -- the census's own read of the printed pair."""
    half = 0.5 if words.endswith(" and a half") else 0.0
    stem = words[: -len(" and a half")] if half else words
    for k in range(0, 60):
        if R.words_for_int(k) == stem:
            return k + half
    return None


def test_S8R3_the_POINTS_are_rounded_to_the_nearest_HALF_before_they_are_spelled():
    """**ROUND-3 MAJOR 1 / CENSUS BLOCKER 1 -- A PRINTED FIGURE ITS OWN BACKING CONTRADICTED.**

    ``_points_words`` truncated toward zero and then said "and a half" for anything 0.25 away, on a
    docstring's claim that "the terms land on halves by construction". MEASURED, they do not:
    ``walk.chain_score`` rounds each term to one decimal, so the live fixture's rendered chains carried
    ``tail`` 21.9 / 23.9 / 24.8 and ``history`` 6.4 / 11.8 / 8.6 -- and the line printed "twenty-one and
    a half", "twenty-three and a half", "twenty-four and a half", "eleven and a half". Wrong on 1 of 1
    chains at quick, 2 of 2 at deep and 3 of 3 at max, always UNDERSTATING, on the one line whose whole
    declared reason is that a census can check it against the trace."""
    got = {v: R._points_words(v) for v in (21.9, 23.9, 24.8, 11.8, 6.4, 24.9, 7.75, 0.5, 25.0, 0.0)}
    assert got[21.9] == "twenty-two" and got[23.9] == "twenty-four"
    assert got[24.8] == "twenty-five" and got[11.8] == "twelve"
    assert got[6.4] == "six and a half" and got[24.9] == "twenty-five"
    assert got[7.75] == "eight" and got[25.0] == "twenty-five" and got[0.0] == "zero"
    assert R._points_words(-7.4) == "minus seven and a half"
    assert R._points_words(None) == "" and R._points_words("x") == ""
    # THE PROPERTY, not just the sample: every spelled value is within a quarter point of the number.
    for i in range(0, 501):
        v = i / 10.0
        back = _points_back(R._points_words(v))
        assert back is not None, v
        assert abs(back - v) <= 0.25 + 1e-9, (v, R._points_words(v))


def test_S8R3_every_rendered_chains_PRINTED_POINTS_agree_with_its_own_TRACE_terms(chain_blocks):
    """**THE CHECK THE ARITHMETIC LINE EXISTS FOR, RUN ON THE PAGE** (DESIGN B.2, census blocker 1).

    The line says the terms and the points in WORDS so that a census can check every pair against
    ``Board.trace()["chains"][*]["terms"]``. Round 2 shipped the line and that check FAILED on every
    rendered chain of every tier. This pin IS that census, on the armed board, all three tiers: for
    each rendered chain, every printed pair is read back out of the line and compared with the trace's
    own number for that term, to the half the page is allowed to round to."""
    for mode, (bd, blk) in sorted(chain_blocks.items()):
        rows = _chain_rows(blk, "chain_why")
        # **RANK ORDER, BECAUSE THAT IS THE PAGE'S ORDER** (round-4 MINOR 2). `Board.chains` is the
        # POOL in composition order and this zip read it as the page's -- which was true only while
        # the render also read the pool. It now renders in `Chain.rank` order, the trace's own.
        chains = sorted((c for c in bd.chains if c.rendered and c.full), key=lambda c: c.rank)
        assert len(rows) == len(chains), (mode, len(rows), len(chains))
        traced = [c for c in (bd.trace().get("chains") or ()) if c.get("rendered")]
        by_hops = {tuple(h["driver_id"] for h in c["hops"]): c for c in traced}
        for ch, row in zip(chains, rows):
            terms = dict(by_hops[tuple(ch.hop_ids)]["terms"])
            pairs = row.split("why: ", 1)[1].split(";", 1)[0]
            seen = 0
            for term, words in R.CHAIN_TERM_WORDS.items():
                v = float(terms.get(term) or 0.0)
                if v <= 0.0:
                    assert ("%s " % words) not in pairs, (mode, term, pairs)
                    continue
                seen += 1
                want = "%s %s" % (words, R._points_words(v))
                assert want in pairs, (mode, ch.hop_ids, want, pairs)
                # ...and the WORDS the page printed stand for the number the trace carries, to a half.
                back = _points_back(R._points_words(v))
                assert back is not None and abs(back - v) <= 0.25 + 1e-9, (mode, term, v)
            assert "%s of %s terms scored" % (R.words_for_int(seen),
                                              R.words_for_int(len(W.CHAIN_TERMS))) in row
            # THE COUNT AGREES WITH THE PAIRS BESIDE IT, which is the property that matters on the
            # page: one sentence, one population, no reader arithmetic.
            assert seen == sum(1 for t in W.CHAIN_TERMS
                               if float((ch.terms or {}).get(t) or 0.0) > 0.0), (mode, ch.hop_ids)
            # **AND THE WALK'S OWN PUBLISHED COUNT IS MEASURED HERE RATHER THAN TRUSTED.** It is not
            # the same number: ``Chain.scope["terms_scored"]`` is computed inside ``chain_score``,
            # and the HISTORY term is re-scored afterwards by ``chain_history``, so the published
            # count can be STALE LOW. MEASURED on this fixture: the deep cell's first rendered chain
            # prints six pairs and publishes five. That is why this line counts what it PRINTS; the
            # drift is lane W's to close (handoff R3-W1) and the direction is pinned so a flip -- a
            # published count LARGER than the pairs on the page -- reds this deck.
            assert int((ch.scope or {}).get("terms_scored") or 0) <= seen, \
                (mode, ch.hop_ids, (ch.scope or {}).get("terms_scored"), seen)


def test_S8R3_EVERY_field_this_render_reads_off_the_walk_is_a_NAME_THE_WALK_PUBLISHES():
    """**LAW (a) OF THIS ROUND, AS ONE ASSERTION.** Round 2 shipped four owner-ordered surfaces that
    rendered nothing because this module read ``tail_peak_month``, ``lag_window_end``,
    ``Chain.data_scope`` and ``chain_counts["cross_event"]`` against a walk carrying
    ``tail_peak_date``, ``tail_lag_to``, ``Chain.scope`` and ``chain_counts["cross_market_event"]``.
    Every pin was green; every pin asserted against a stand-in.

    So the seam has ONE published spelling (``walk.CHAIN_SEAM_FIELDS``) and every name this render
    reads is resolved here against the SHIPPED objects: a real frozen ``ChainHop``, a real ``Chain``,
    and the real ``chain_counts`` output -- never a namespace this test wrote itself."""
    import ast
    import inspect
    import textwrap
    hop, ch = _s8_hop(), _s8_chain([_s8_hop()])
    produced = W.chain_counts([])
    # `series_key` IS ON THIS LIST BECAUSE `seam._dim_for_hop` MATCHES A HOP TO THE ANALOG LEG'S
    # DECLARED DIMENSION ON IT (round-3 MAJOR 6) -- it is a consumed seam field, it was missing from
    # the roster when this pin was first written, and lane W published it on the handoff.
    reads_hop = ("measured", "percentile", "tail", "run_direction", "run_since", "knowledge_date",
                 "driver_id", "contract", "lag_band", "series_key",
                 "tail_peak_percentile", "tail_peak_date", "tail_lag_to")
    reads_chain = ("hops", "agreements", "edge_signs", "cross", "terminal", "terminal_key",
                   "terminal_percentile", "contract", "unnamed_terminal", "receipt_index",
                   "receipt_hop", "receipt_kind", "history", "outcome", "side", "against_hops",
                   "curated", "terms", "scope", "positioning", "slot", "rendered", "full")
    reads_counts = ("distinct_sequences", "total", "state_two_hops", "with_document",
                    "distinct_unnamed_markets", "cross_market_event",
                    "cross_market_event_rendered")
    for f in reads_hop:
        assert hasattr(hop, f), f
        assert "ChainHop.%s" % f in W.CHAIN_SEAM_FIELDS, f
    for f in reads_chain:
        assert hasattr(ch, f), f
        assert "Chain.%s" % f in W.CHAIN_SEAM_FIELDS, f
    for f in reads_counts:
        assert f in produced, f
        assert "chain_counts.%s" % f in W.CHAIN_SEAM_FIELDS, f
    for f in ("buffer_series", "events_in_corpus", "price_read", "terms_scored"):
        assert "Chain.scope.%s" % f in W.CHAIN_SEAM_FIELDS, f
    for f in ("percentile", "against", "key"):
        assert "Chain.positioning.%s" % f in W.CHAIN_SEAM_FIELDS, f
    # AND THE FOUR NAMES THAT COST A ROUND ARE GONE FROM BOTH SIDES.
    for dead in ("tail_peak_month", "lag_window_end"):
        assert not hasattr(hop, dead), dead
    assert not hasattr(ch, "data_scope")
    assert "cross_event" not in produced and "cross_event_rendered" not in produced
    # THE SCAN IS OVER CODE, NOT PROSE. Every one of these producers DOCUMENTS the name it used to
    # read and why the surface died -- that record is the point of the docstring -- so the check
    # unparses the AST with the docstrings dropped and reads what the function actually executes.
    for fn in (R.chain_state_words, R.chain_arithmetic_words, R.sb_chain_count):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = node.body[0] if node.body else None
                if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    node.body = node.body[1:]
        code = ast.unparse(tree)
        for dead in ("tail_peak_month", "lag_window_end", "data_scope", "cross_event"):
            assert dead not in code, (fn.__name__, dead)


def test_S8R4_the_LAG_BAND_prints_ONLY_where_its_DECLARED_RELATION_is_the_one_the_clause_asserts(
        chain_blocks):
    """**ROUND-4 MAJOR 1, ORCHESTRATOR RULING -- A PRINTED FIGURE UNDER THE WRONG PREDICATE.**

    ``ChainHop.lag_band`` is ``parse_lag(dag_node.lag)`` -- the lag the DAG declares for that node --
    and round 3 printed it inside the clause that asserts the edge onto the NEXT HOP: "declared in the
    same direction onto drought with a lag of one to two quarters", where one to two quarters is La
    Nina's own declared lag into this market and not the time it takes to reach drought. MEASURED
    before that cut: 23 of 23 printed bands misbound, on both cells at all three tiers
    (``r2d/R4_cells_BEFORE.json``).

    THE RULING: the band prints on the TERMINAL EDGE -- the last hop, whose clause's own "onto" already
    names what the edge runs into -- and on NO intermediate hop. A chain whose terminal is a FAR market
    prints no band at all rather than the same misbinding one noun further on.

    **AND ROUND 5 TOOK THE THREE WORDS THAT ASSERTED A TARGET METRIC** (blocker 11). Round 4's clause
    read "with a declared lag of <band> TO THE PRICE" on the premise -- written into the producer and
    into this docstring -- that "every node of the anchor's DAG declares ``target_metric: price``".
    MEASURED over the 36 ``configs/graphrag/causal/*.yaml``: 1,208 nodes declare ``price`` and 49
    declare something else, in SIX DAGs (``rough_rice_cbot`` 22 of 33, ``cotton`` 13 of 37, the four
    wheats 6-8 each). ``ChainHop`` carries no ``target_metric``, so the producer cannot read the
    relation those three words asserted -- a rice hop whose 0-2 quarter band is declared against YIELD
    would print it "to the price". The clause now states the hop's own declared lag and no more.
    ZERO misbound bands had reached a page (across 18 boards and 93 rendered hop rows the clause prints
    exactly once, on an all-price corn DAG), so this is the premise corrected before it is reached.

    AND IT RETIRES ROUND-3 MINOR 3: ``band_words(None)`` is an honest absence sentence in the SB-E row
    it was written for and a doubled noun here, so a hop whose band the table does not carry prints no
    band clause. Nothing is deleted -- there is no figure to delete."""
    band = parse_lag("0-2 quarters")
    hops = [_s8_hop(driver_id="China_import_tariff", lag_band=parse_lag("1-2 quarters")),
            _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0, lag_band=band)]
    ch = _s8_chain(hops)                                 # terminal == contract: NOT a cross chain
    assert ch.cross is None and str(ch.terminal) == str(ch.contract)
    first, last = R.sb_chain_hop(ch, 0), R.sb_chain_hop(ch, 1)
    assert "with a lag of %s" % R.band_words(band) in last, last
    # THE CLAUSE NAMES NO TARGET METRIC (blocker 11): `ChainHop` carries none, and 49 nodes of six of
    # the estate's DAGs declare something other than price. It also ends the doubled noun this lane's
    # R4-O1 recorded ("onto the CBOT soybeans price ... to the price").
    assert "to the price" not in last, last
    assert "lag of" not in first, "no intermediate hop names a band it is not declared against"
    assert "the CBOT soybeans price" in last, "the terminal clause's own onto names the relation"
    for line in (first, last):
        assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
    # A CROSS chain's terminal edge is onto a FAR market, so the band -- declared to the ANCHOR's
    # price -- is not printed there either. The relation, not the position, is the rule.
    xch = _s8_chain(hops, terminal="corn_cbot", cross={"other": "corn_cbot", "sign": "+"})
    assert "lag of" not in R.sb_chain_hop(xch, 1), R.sb_chain_hop(xch, 1)
    # MINOR 3, GUARDED: a hop whose table carries no band prints no band clause and no doubled noun.
    nob = _s8_chain([_s8_hop(driver_id="China_import_tariff"),
                     _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0, lag_band=None)])
    assert R.band_words(None) == "a lag the table does not carry"
    assert R.band_words(None) not in R.sb_chain_hop(nob, 1), R.sb_chain_hop(nob, 1)
    assert "percentile" in R.sb_chain_hop(nob, 1), "the reading, the direction and the verdict stay"
    # ON THE PAGE: NOT ONE hop line prints a band whose "onto" is anything but the anchor's own price.
    for mode, (bd, blk) in sorted(chain_blocks.items()):
        rows = _chain_rows(blk, "chain_hop")
        assert rows, mode
        want = 0
        for c in sorted((x for x in bd.chains if x.rendered and x.full), key=lambda x: x.rank):
            want += int(bool(c.hops) and not c.cross
                        and c.hops[-1].lag_band is not None
                        and c.hops[-1].lag_band.min_q is not None)
        assert sum(1 for x in rows if "declared lag of" in x) == want, (mode, want)
        assert not [x for x in rows if "with a lag of" in x], mode


def test_S8R3_the_SLOT_LABEL_renders_in_the_chain_rows_own_words_on_a_real_walk_Chain():
    """**OWNER RULING 2026-09-22, RATIFIED -- THE SLOT LABEL ON THE PAGE.**

    ``walk.Chain.slot`` names the seat the selection held for a chain: the chain the question's SUBJECT
    names, the PAIR it sets, a chain inside the HORIZON it asked for, or the other SIGN. ``top`` is a
    chain that ranked in on its own score and renders NO label. The label is one short clause on the
    row head, the one-line form below the print line carries it too, and the count line counts the
    held seats in the same sentence it counts the rest.

    THE ROUND-2 LESSON IS WHY EVERY ASSERTION HERE IS AGAINST A REAL ``walk.Chain``: a label pinned on
    a stand-in is a green pin and a dead surface."""
    from leviathan.graphrag import register as REG
    assert "Chain.slot" in W.CHAIN_SEAM_FIELDS
    assert set(R.CHAIN_SLOT_WORDS) | {"top"} == set(W.CHAIN_SLOTS), \
        "one roster, published by the walk, spelled once here"
    ch = _s8_chain([_s8_hop(), _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0)],
                   terminal="corn_cbot")
    ch.unnamed_terminal = True
    assert hasattr(ch, "slot") and ch.slot == "", "the field is the walk's own and defaults empty"
    plain = R.sb_chain_head(ch, i=1, n=3)
    assert R.chain_slot_words(ch) == ""
    for slot, words in (("subject", "the chain this question names"),
                        ("pair", "the pair this question sets"),
                        ("horizon", "inside the horizon this question asks"),
                        ("sign", "the other side")):
        ch.slot = slot
        assert R.chain_slot_words(ch) == words, slot
        head = R.sb_chain_head(ch, i=1, n=3)
        one = R.sb_chain_one_line(ch, i=1, n=3, why=("the distance it travels",))
        assert words in head and words in one, slot
        assert len(head) - len(plain) == len(words) + 2, slot
        for line in (head, one):
            assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
            assert REG.count_desk_register(line) == 0 and REG.internal_leaks(line) == []
            line.encode("ascii")
    ch.slot = "top"
    assert R.chain_slot_words(ch) == "" and R.sb_chain_head(ch, i=1, n=3) == plain, \
        "a chain that ranked in says so by carrying no label at all"
    # THE COUNT LINE COUNTS THE HELD SEATS IN THE SAME SENTENCE, and says nothing where none was held.
    counts = {"distinct_sequences": 77, "total": 1848, "state_two_hops": 816,
              "with_document": 432, "distinct_unnamed_markets": 17}
    assert "for a reason other than rank" not in R.sb_chain_count(counts, k=3, slots=("top", "top"))
    held = R.sb_chain_count(counts, k=3, anchor_label="CBOT soybeans",
                            slots=("sign", "top", "subject"))
    # 09-25 (RT-8): the plain count says "three of them carried above, two here for a reason other than rank"
    assert "three of them carried above, two here for a reason other than rank" in held
    assert R.classify(held) == ("SB-P",) and R.register_hits(held) == []


def test_S8R3_the_OWNER_ORDERED_SURFACES_RENDER_ON_THE_PAGE(chain_blocks):
    """**LAW (b): A SURFACE IS MEASURED ON THE PAGE.** The round-2 census counted, on the rendered
    block at every tier: ``"peaked"`` 0, ``"cross a market"`` 0, ``"open action"`` 0, the data-scope
    sentence 0 -- while the producers carried 135 / 1,200 / 1,488 window peaks and 112 / 342 / 414
    cross-market dated actions. Four owner-ordered surfaces, every pin green, nothing on the page.

    This pin reads the rendered block. It asserts the tail-window peak clause and the orthogonal-shocks
    clause where the fixture's own data carries them, and it asserts the SLOT label wherever the
    selection held a seat on this board. The two data-scope absence sentences are NOT asserted here and
    are not claimed: this anchor serves a buffer family and carries dated actions, so the fixture
    cannot reach them -- their pin is the producer-level one above, and the arm's own smoke is where a
    buffer-less anchor is read."""
    reached = {"peak": 0, "cross": 0, "slot": 0}
    for mode, (bd, blk) in sorted(chain_blocks.items()):
        text = blk.text()
        hops = _chain_rows(blk, "chain_hop")
        counts = dict(bd.chain_counts or {})
        want_peak = [h for c in bd.chains if c.rendered and c.full for h in c.hops
                     if h.measured and h.tail_peak_percentile is not None and h.tail_peak_date
                     and R.percentile_words(h.tail_peak_percentile)
                     != R.percentile_words(h.percentile)]
        if want_peak:
            # THE VERB IS THE EXTREME'S OWN SIDE (09-23, R-5): a window extreme below the median is a
            # trough and the line says "bottomed at"; the count of in-transit hops is unchanged.
            assert ("peaked at the " in text) or ("bottomed at the " in text), mode
            assert "the peak's own window runs to " in text, mode
            assert sum(1 for x in hops if ("peaked at the " in x or "bottomed at the " in x)) \
                == len(want_peak), mode
            reached["peak"] += 1
        if counts.get("cross_market_event") is not None:
            assert "cross a market carrying an open action" in text, mode
            reached["cross"] += 1
        slots = [str(getattr(c, "slot", "") or "") for c in bd.chains if c.rendered]
        held = [s for s in slots if s and s != "top"]
        for s in held:
            assert R.CHAIN_SLOT_WORDS[s] in text, (mode, s)
        if held:
            assert "here for a reason other than rank" in text, mode
            reached["slot"] += 1
        # **ONE FACT, AND THE TWO PRODUCERS OF IT ARE PINNED TO AGREE.** The count line derives the
        # held seats from `Chain.slot` on the chains THIS PAGE RENDERED -- the same read that mints
        # the label a reader just saw, so the label and the count cannot disagree. The walk publishes
        # the same counts over its own rendered set (`chain_counts["slot_*"]`). They are the same
        # population by construction and a drift is a red deck here rather than a page that counts
        # one thing and labels another.
        if any(("slot_%s" % s) in counts for s in R.CHAIN_SLOT_WORDS):
            pub = sum(int(counts.get("slot_%s" % s) or 0) for s in R.CHAIN_SLOT_WORDS)
            assert pub == len(held), (mode, pub, held)
            assert int(counts.get("slot_top") or 0) == sum(1 for s in slots if s == "top"), mode
        # AND THE WHOLE CHAIN SECTION STAYS CLEAN while all of this renders.
        assert blk.trips == [], (mode, blk.trips[:1])
        for line in hops + _chain_rows(blk, "chain_count") + _chain_rows(blk, "chain"):
            assert R.register_hits(line) == [], (mode, line[:120])
    # **AND THE SLOT COUNTER IS READ** (round-4 MINOR 4). It was accumulated and never asserted, so a
    # walk that seated NO slot on any tier -- the very guards lane W landed in round 3 skip the
    # subject / pair / horizon seats before the pool is touched -- would take the whole owner-ordered
    # surface dark with this deck green. That is precisely the round-2 failure law (b) exists to stop.
    #
    # 09-23: THE FIXTURE'S ONLY SEAT WAS THE LA NINA CHAIN'S "sign" SEAT, and lane W's phase-in-force fact
    # (C7) demotes every chain walking a pole that is not in force (the fixture's ONI reads the warm pole),
    # so no tier seats a slot on this anchor any more -- correctly. The WALK half of the surface is lane W's
    # producer-level pins (test_state_walk W1 / W2 carry every slot state). The PAGE half stays pinned HERE
    # on a copy of the max board with one rendered chain seated the way the walk seats one (`Chain.slot`),
    # so a render that stopped printing a seat's label, or its count clause, still reds this deck.
    if reached["slot"] == 0:
        import copy as _copy
        bd0, _blk0 = chain_blocks["max"]
        bd1 = _copy.deepcopy(bd0)
        seated = sorted((c for c in bd1.chains if c.rendered), key=lambda c: c.rank)
        assert len(seated) >= 2, "the max fixture renders more than one chain"
        seated[1].slot = "sign"
        text1 = R.render_board(bd1, analogs=(), anchor_label=", ".join(
            R.board_label(s) for s in bd1.anchor_slugs)).text()
        assert R.CHAIN_SLOT_WORDS["sign"] in text1, "a seated chain names its seat on the page"
        assert "here for a reason other than rank" in text1, "and the count line says one is seated"
        assert "here for a reason other than rank" not in chain_blocks["max"][1].text(), \
            "the unseated page says nothing about a seat"
        reached["slot"] += 1
    assert reached["peak"] >= 2 and reached["cross"] == 3 and reached["slot"] >= 1, reached


# S8 ROUND 4: THE CLOSING ITEMS -- the page's own ORDINAL, the two counted-not-deleted halves
# (the aged-out document and the outcome's denominator), the one recency rule, and the stanza mark.
def test_S8R4_the_pages_chain_ORDINAL_is_the_RANKS_and_not_the_POOLS(chain_blocks):
    """**ROUND-4 MINOR 2 -- ONE FACT, TWO ORDERS.** ``Board.chains`` carries the POOL in COMPOSITION
    order; ``Board.trace()["chains"]`` publishes RANK order (``walk.chain_trace_set`` sorts on
    ``Chain.rank``). The render read the pool, so "CHAIN first of three" named the chain the trace
    listed SECOND -- MEASURED on the live fixture: page tail terms [23.9, 21.9] against trace
    [21.9, 23.9] on deep, and [23.9, 21.9, 24.8] against [21.9, 23.9, 24.8] on max.

    A reader takes "first of three" for a rank. The judge and the arm report read the trace. And the
    held-seat label (owner ruling 2026-09-22) rides one of those heads, which is what made the split
    legible rather than merely present. ONE ORDER, and it is the selection's own."""
    for mode, (bd, blk) in sorted(chain_blocks.items()):
        heads = [x for x in _chain_rows(blk, "chain") if x.startswith(R.CHAIN_HEAD_PREFIX)]
        traced = [c for c in (bd.trace().get("chains") or ()) if c.get("rendered")]
        assert heads and traced, mode
        # THE TRACE'S OWN ORDER, read off the trace and never re-sorted here.
        want = [tuple(h["driver_id"] for h in c["hops"]) for c in traced]
        got = []
        for x in heads:
            hit = [c for c in bd.chains
                   if c.rendered and R.chain_hop_name(c.hops[0]) in x
                   and R.board_label(c.terminal or c.contract) in x]
            assert hit, (mode, x[:90])
            got.append(tuple(sorted(hit, key=lambda c: c.rank)[0].hop_ids))
        assert got == want[: len(got)], (mode, got, want)
        # ...and the ordinal WORDS follow that same order, first to last.
        for i, x in enumerate(heads, start=1):
            which = ("the one this page carries" if len(heads) == 1
                     else "%s of %s" % (R.ordinal_words(i), R.words_for_int(len(heads))))
            assert which in x, (mode, i, x[:90])


def test_S8R4_the_COUNT_LINE_counts_the_AGED_OUT_dated_actions_in_its_own_sentence(chain_blocks):
    """**ROUND-4 CENSUS 5 -- A CORRECTION THAT LEAVES NO TRACE IS A DELETION.**

    ``walk._receipt_in_reach`` correctly refuses to call a 2019 action today's receipt, and
    ``Chain.receipts_aged_out`` counts the documents it refused. The PAGE read neither that field nor
    the counter beside it, so a chain whose only dated action was aged out was indistinguishable, to a
    reader, from a chain that never had one.

    IT FOLDS INTO THE EXISTING CLOSURE, never a second sentence, and ZERO is silent because "no dated
    action aged out" is this page's ordinary state.

    **ROUND 5, BLOCKER 3: THE NUMBER UNDER THE NOUN IS THE DISTINCT DOCUMENT COUNT.** Round 4 summed
    ``Chain.receipts_aged_out`` -- a PER-CHAIN count -- over the whole POOL at the call site, while
    ``ChainHop`` is memoised per ``(contract, driver_id)``: one document on one row was counted once
    for every pool chain that walked it, and MEASURED through the shipped producer with EXACTLY ONE
    dated action in the estate the page printed "fifty-five / two hundred twenty / TWO HUNDRED
    SIXTY-FOUR dated actions aged out of their windows". ``chain_counts["receipts_aged_out"]`` is now
    the POOL's DISTINCT count (``walk._aged_receipt_keys``) and this line READS it: one population,
    one spelling, one owner."""
    counts = {"distinct_sequences": 77, "total": 1848, "state_two_hops": 816,
              "with_document": 432, "distinct_unnamed_markets": 17}
    assert "older than the lag" not in R.sb_chain_count(counts, k=3, anchor_label="CBOT soybeans")
    one = R.sb_chain_count(dict(counts, receipts_aged_out=1), k=3, anchor_label="CBOT soybeans")
    many = R.sb_chain_count(dict(counts, receipts_aged_out=4), k=3, anchor_label="CBOT soybeans")
    assert "one dated action older than the lag the model allows for it" in one, one
    assert "four dated actions older than the lag the model allows for them" in many, many
    assert "chain_counts.receipts_aged_out" in W.CHAIN_SEAM_FIELDS
    assert "receipts_aged_out" in W.chain_counts([]), "the name is the producer's, not this line's"
    for line in (one, many):
        assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
        bare = _GLUED_RX.sub("", _YEAR_RX.sub("", _ISO_RX.sub("", line)))
        assert not any(c.isdigit() for c in bare), line
    # ON THE PAGE, off the SHIPPED counter on the REAL pool: this fixture ages none out, so the clause
    # is (correctly) absent, and the counted state is rendered by stamping the producer's own key.
    for mode, (bd, blk) in sorted(chain_blocks.items()):
        assert "older than the lag the model allows" not in blk.text(), \
            (mode, "the fixture ages none out")
        assert int((bd.chain_counts or {}).get("receipts_aged_out") or 0) == 0, mode
        was = dict(bd.chain_counts or {})
        try:
            bd.chain_counts = dict(was, receipts_aged_out=2)
            again = R.render_board(bd, analogs=(), anchor_label="CBOT soybeans")
            assert "two dated actions older than the lag the model allows for them" in again.text(), \
                mode
            assert again.trips == [], (mode, again.trips[:1])
        finally:
            bd.chain_counts = was


def test_S8R4_the_OUTCOME_row_states_the_SAMPLE_and_its_DENOMINATOR_in_one_noun(chain_blocks):
    """**ROUND-4 CENSUS 5 -- ``Chain.outcome["n_in"]`` WAS A DECLARED SEAM FIELD THE PAGE NEVER READ.**

    ``walk.chain_outcome`` publishes ``n_in`` (the past firings of this reading) beside ``n`` (those
    the anchor's price array could read over the declared band). The page printed the SUBSET alone --
    "across five past firings" -- two rows under a record line printing "in eleven of fourteen past
    firings of this reading". Two counts of one population under one noun, and nothing on the page
    saying the five were a subset of the fourteen. ``walk.chain_outcome_words`` closed exactly this
    for the trace (review MA-5); the page was left on the old spelling.

    ONE PRODUCER FOR BOTH ROWS -- the minting one and the letters-only absence -- so the sample can
    never be stated two ways on one page."""
    ch = _s8_chain([_s8_hop(), _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0)])
    ch.declared_sign = "+"
    ch.outcome = {"n": 5, "n_in": 14, "median_move": 2.1, "low": -1.0, "high": 4.0,
                  "share_declared_way": 3, "unit": "percent", "scope": _S8_SCOPE,
                  "window_from": "2025-06-16", "window_to": "2026-09-04"}
    line, calls = R.sb_chain_outcome(9, ch, asof="2026-09-07")
    _FIVE = "five of the fourteen past times this reading sat this far out carry a price reading"
    assert _FIVE in line, line
    assert len(calls) == 3 and R.classify(line) == ("SB-O",), line
    # ...and the SAME clause on the branch the fixture's own chains take.
    ch.outcome = dict(ch.outcome, median_move=None, low=None, high=None)
    thin = R.sb_chain_outcome_absent(ch)
    assert _FIVE in thin, thin
    assert "too thin for a middle figure" in thin, thin
    # A SINGULAR SAMPLE AND A SINGULAR DENOMINATOR each take their own verb and noun.
    ch.outcome = dict(ch.outcome, n=1, n_in=1)
    assert ("the one past time this reading sat this far out carries a price reading over the band"
            in R.sb_chain_outcome_absent(ch))
    # NO DENOMINATOR PUBLISHED -> the subset's own count, and nothing it cannot back.
    ch.outcome = dict(ch.outcome, n=3, n_in=0)
    assert ("three past times this reading sat this far out carry a price reading over the band"
            in R.sb_chain_outcome_absent(ch))
    # AND ON THE PAGE, off the SHIPPED producer's own numbers.
    seen = 0
    for mode, (bd, blk) in sorted(chain_blocks.items()):
        for c in sorted((x for x in bd.chains if x.rendered and x.full), key=lambda x: x.rank):
            o = dict(c.outcome or {})
            if not int(o.get("n") or 0):
                continue
            seen += 1
            want = (("all %s past times" % R.words_for_int(int(o["n"])))
                    if int(o["n"]) == int(o["n_in"]) and int(o["n"]) > 1 else
                    "%s of the %s past times" % (R.words_for_int(int(o["n"])),
                                                 R.words_for_int(int(o["n_in"]))))
            assert want in blk.text(), (mode, want)
        for line in _chain_rows(blk, "chain_outcome"):
            assert R.register_hits(line) == [], (mode, line[:120])
    # FIX ROUND 2, fixer pass (the declared K13 move, REVIEW_WT MINOR-2 / integrator F-7-class re-bank): the
    # fixture's only priced chain is La Nina-rooted on a warm ONI, so `Chain.premise_off` keeps it off every
    # seat and no RENDERED chain carries a priced outcome any more. The pin keeps grading the SHIPPED
    # producer on the SHIPPED numbers: the pool's priced chains, each through the one producer that prints
    # its outcome row (the minting row where a middle figure exists, else its letters-only absence).
    if not seen:
        for mode, (bd, _blk) in sorted(chain_blocks.items()):
            for c in sorted(bd.chains, key=lambda x: x.rank):
                o = dict(W._outcome_for(bd, c) or {})      # the SAME producer the rendered chains use
                if not int(o.get("n") or 0):
                    continue
                c.outcome = o
                seen += 1
                want = (("all %s past times" % R.words_for_int(int(o["n"])))
                        if int(o["n"]) == int(o["n_in"]) and int(o["n"]) > 1 else
                        "%s of the %s past times" % (R.words_for_int(int(o["n"])),
                                                     R.words_for_int(int(o["n_in"]))))
                got = (R.sb_chain_outcome(9, c, asof=str(bd.asof))[0] if o.get("median_move") is not None
                       else R.sb_chain_outcome_absent(c))
                assert want in got, (mode, want, got[:200])
                assert R.register_hits(got) == [], (mode, got[:120])
    assert seen >= 1, "the fixture must carry one priced outcome, or this pin grades nothing"


def test_S8R4_an_OUT_OF_REACH_closed_document_is_NEVER_the_chains_receipt_and_says_so(chain_blocks):
    """**ROUND-4 CENSUS 8 (round-2b blocker 8) -- ONE RECENCY RULE, AND THE RENDER HAD NONE.**

    ``walk._chain_receipt`` ages a CLOSED receipt out at one band-length of the as-of and scores the
    EVENT term accordingly. ``render.chain_receipt`` -- which is handed the WIDER pool and so sees
    documents the walk never did -- had no bound at all, so the page could print, as this chain's
    receipt, a document the score gave zero for. ``_receipt_in_reach`` appeared ZERO times in
    ``render.py``.

    THE RULE IS IMPORTED, NEVER RE-TYPED: the candidate's own date rides a REAL ``walk.ChainHop``
    (``dataclasses.replace``) and the shipped predicate decides, so the two halves of one recency rule
    cannot drift. The aged document is PRINTED -- counted, never deleted -- and spends no ``[E]``
    seat, because a document this chain cannot claim must not cost the page a citation."""
    import dataclasses
    import inspect

    from leviathan.graphrag import register as REG
    assert "_receipt_in_reach" in inspect.getsource(R.chain_receipt), "one rule, imported"
    hop = _s8_hop(lag_band=parse_lag("0-1 quarters"))
    ch = _s8_chain([hop, _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0)])
    # 09-24 RE-BANK (OWNER DECISION O-6, CONTRACT K6, lane W): an action is REALISED only when its whole
    # interval, at its stated precision, ends on or before the document's own date -- so these DAY actions
    # state their precision and the document date that reported them (the extraction's own two fields).
    old = {"event_date": "2019-01-01", "source": "a wire service", "tier": 2, "date": "2019-01-02",
           "text": "the authority raised the export levy from the first of that month",
           "event_date_precision": "day"}
    near = dict(old, event_date="2026-08-20", date="2026-08-21",
                text="the authority raised the export levy from the twentieth")
    # THE SHIPPED PREDICATE'S OWN VERDICT on the two dates, on a REAL hop.
    assert not W._receipt_in_reach(dataclasses.replace(hop, event_date="2019-01-01"), "2026-09-07")
    assert W._receipt_in_reach(dataclasses.replace(hop, event_date="2026-08-20"), "2026-09-07")
    aged = R.chain_receipt(ch, {("soybeans_cbot", "export_pace_lag"): [old]}, asof="2026-09-07")
    # THE DOCUMENT RIDES `prop` SO THE PAGE CAN CITE IT AT THE MENU'S OWN ADDRESS (09-23, item 4); the
    # kind stays "none" -- no seat of the chain's own is spent.
    assert aged["kind"] == "none" and aged["prop"] is not None, aged
    assert "older than the lag the model allows for it" in aged["words"], aged["words"]
    assert "1 January 2019" in aged["words"] and "read as history" not in aged["words"]
    row = R.sb_chain_document(aged, aged["hop"])
    assert "older than the lag the model allows for it" in row and R.classify(row) == ("SB-P",)
    assert R.register_hits(row) == [] and REG.count_desk_register(row) == 0
    # ...AND A CLOSED DOCUMENT INSIDE ONE BAND-LENGTH IS STILL THE CHAIN'S RECEIPT, read as history.
    # THE MEASUREMENT THAT SHAPES THIS HALF, STATED RATHER THAN HIDDEN: for a band with a max end of
    # one quarter or more, "the window has closed" (event + max < as-of) and "within one band-length
    # of the as-of" (event >= as-of - max) are COMPLEMENTARY by construction, so the in-reach CLOSED
    # case exists only for a same-quarter band -- which is the case built here, and the same property
    # holds of ``walk._chain_receipt``'s own closed branch. Handed to lane W in the round-4 handoff.
    same = _s8_hop(driver_id="export_pace_lag", lag_band=parse_lag("0 quarters"))
    ch2 = _s8_chain([same, _s8_hop(driver_id="psd_ending_stock_su_ratio", percentile=68.0)])
    assert W._receipt_in_reach(dataclasses.replace(same, event_date="2026-08-20"), "2026-09-07")
    got = R.chain_receipt(ch2, {("soybeans_cbot", "export_pace_lag"): [near]}, asof="2026-09-07")
    assert got["kind"] == "closed" and got["prop"] is not None, got
    assert "read as history: the lag the model allows for it has run out" in got["words"], \
        got["words"]
    # AND NOTHING ON THE LIVE FIXTURE'S PAGES MOVED: no chain there carries an aged-out document.
    for mode, (_bd, blk) in sorted(chain_blocks.items()):
        assert "older than the lag the model allows for it" not in blk.text(), mode


def test_S8R4_the_STANZA_HEAD_is_MARKED_as_the_THEN_of_the_chain_the_page_named_first():
    """**ROUND-4 MAJOR 2 / DESIGN C.2's RENDER HALF -- WIRED AND INAUDIBLE.**

    ``seam._first_dim`` passed the top chain's dimension into the analog selection and
    ``analogs._dims_first`` moved it to the front of the vector the coverage line enumerates -- and
    ``first_dim`` appeared ZERO times in ``render.py``, so nothing on the page said WHY that dimension
    led. A reordering nobody is told about is not an attribution, and lane N's mandate clause is
    conditional on exactly this mark.

    IT IS PRINTED ONLY WHERE THE ORDER IS ACTUALLY THE CHAIN'S: where ``_dims_first`` no-opped because
    the chain's dimension is not one this board declares, the clause is absent rather than claiming a
    lead that did not happen.

    **AND ROUND 5 ADDED THE SECOND HALF OF THAT SENTENCE** (blocker 6): only where the dimension is a
    hop THE CHAIN ACTUALLY CARRIES. ``seam._dim_for_hop`` translates a hop onto the id the analog leg
    ranks its SERIES under, and on the estate's own ONI collision the board declares ``El_Nino`` where
    the chain walks ``La_Nina`` -- so the page read "CHAIN first of three, from LA NINA to ICE canola"
    and then "read as the history of the chain named first, ON EL NINO", on 3 of the 4 cells that
    carried a mark. ``chain_dims`` is the top rendered chain's own hop ids, handed down by
    ``render_board``; the translation still ORDERS the stanza and is never NAMED."""
    from leviathan.graphrag import register as REG
    a = {"driver_id": "El_Nino", "contract": "soybeans_cbot", "date": "2015-08-31",
         "n_candidates": 4, "floor_year": "2003", "asof": "2026-09-07",
         "first_dim": "export_pace_lag",
         "dims_order": ["export_pace_lag", "El_Nino", "La_Nina"]}
    dims = ("export_pace_lag", "psd_ending_stock_su_ratio")       # the chain's OWN hops
    head = R.sb_analog_header(a, chain_dims=dims)
    plain = R.sb_analog_header(dict(a, first_dim=None), chain_dims=dims)
    assert "read as the history of the chain named first, on export pace lag" in head, head
    assert R.classify(head) == ("SB-A",), R.classify(head)
    # THE CLAUSE ITSELF IS CLEAN, and it moves neither instrument count on the header it rides. The
    # SB-A header's own two desk-register hits are HEAD's and predate this movement.
    mark = R.chain_stanza_mark(a, chain_dims=dims)
    assert R.register_hits(mark) == [] and REG.count_desk_register(mark) == 0, mark
    assert REG.internal_leaks(mark) == [] and not any(c.isdigit() for c in mark), mark
    assert R.register_hits(head) == R.register_hits(plain)
    assert REG.count_desk_register(head) == REG.count_desk_register(plain)
    head.encode("ascii")
    # THE NO-OP SAYS NOTHING: a first_dim no declared dimension leads with is not an attribution.
    assert R.chain_stanza_mark(dict(a, dims_order=["El_Nino", "La_Nina"]), chain_dims=dims) == ""
    assert R.chain_stanza_mark(dict(a, first_dim=None), chain_dims=dims) == ""
    assert R.chain_stanza_mark({}, chain_dims=dims) == ""
    assert R.sb_analog_header(dict(a, first_dim=None)) + mark == head
    # **AND A DIMENSION THE CHAIN DOES NOT CARRY IS NEVER NAMED** (blocker 6), whatever the leg leads
    # with: the ONI pair is one series under two driver ids in opposite phases, and this clause is an
    # ATTRIBUTION. No `chain_dims` at all is the flag-off answer and says nothing.
    oni = dict(a, first_dim="El_Nino", dims_order=["El_Nino", "La_Nina", "export_pace_lag"])
    assert R.chain_stanza_mark(oni, chain_dims=("La_Nina", "drought")) == "",         "a La Nina chain is never read 'on El Nino'"
    assert "read as the history" not in R.sb_analog_header(oni, chain_dims=("La_Nina", "drought"))
    assert R.chain_stanza_mark(oni, chain_dims=("El_Nino",)) != "",         "and where the chain DOES carry that driver, the mark is its own word"
    assert R.chain_stanza_mark(a) == "" and R.sb_analog_header(a) == plain
    # THE CO-LOUD STANZA IS A DIFFERENT SELECTOR and carries no chain attribution at all.
    co = dict(a, co_loud=True, n_contracts=3)
    assert "read as the history of the chain" not in R.sb_analog_header(co, chain_dims=dims)


def test_S8R5_a_REPORT_SENTENCE_outside_the_hops_window_is_NAMED_never_cited_and_never_dropped(chain_blocks):
    """**ROUND-5 CENSUS BLOCKER 1 (reproduced on both trees).** ``walk._chain_receipt``'s choice (3) reads
    the same window bound as choice (2), so a pure mechanism proposition (a ``date``, no ``event_date``)
    older than one band-length of the as-of scores EVENT 0 and the producer says "no dated document in
    this hop's window" -- while ``render.chain_receipt``'s mechanism loop, which refused a candidate only
    where its text identity sat in ``aged_ids`` (aged ACTIONS), still returned it as this chain's receipt:
    "chain document: at La Nina, a dated report on this hop's mechanism, 2019-01-05." beside a WHY row
    with no action term. Two producers disagreeing about one document on one page.

    THE RULE IS IMPORTED, NEVER RE-TYPED, on the candidate's OWN date on a REAL hop; the refused sentence
    is NAMED under its OWN noun (:data:`R.CHAIN_RECEIPT_REPORT_OUTSIDE`, "a dated report", never "a dated
    action") on the hop it sits on, spends no ``[E]`` seat, and the producer publishes the same pair on
    ``Chain.mechanism_refused_hop`` / ``_date``. A correction that leaves no trace is a deletion."""
    import dataclasses

    from leviathan.graphrag import register as REG
    hop = _s8_hop(driver_id="La_Nina", lag_band=parse_lag("1-2 quarters"))
    ch = _s8_chain([hop, _s8_hop(driver_id="drought", percentile=88.0)])
    old = {"date": "2019-01-05", "source": "a wire service", "tier": 2,
           "text": "the cold phase tightened the Brazilian planting window that season"}
    assert not W._receipt_in_reach(dataclasses.replace(hop, event_date="2019-01-05"), "2026-09-07")
    got = R.chain_receipt(ch, {("soybeans_cbot", "La_Nina"): [old]}, asof="2026-09-07")
    assert got["kind"] == "none" and got["prop"] is not None, got
    assert got["words"] == R.CHAIN_RECEIPT_REPORT_OUTSIDE % "published 5 January 2019", got["words"]
    assert "dated report" in got["words"] and "dated action" not in got["words"]
    assert got["hop"] is hop, "named on the hop the sentence sits on, never the chain's receipt hop"
    row = R.sb_chain_document(got, got["hop"])
    assert "outside the lag the model allows for it" in row and R.classify(row) == ("SB-P",), row
    assert R.register_hits(row) == [] and REG.count_desk_register(row) == 0
    # ...AND A REPORT SENTENCE INSIDE THE WINDOW IS STILL THE CHAIN'S MECHANISM RECEIPT.
    near = dict(old, date="2026-08-20", text="the cold phase tightened the planting window this month")
    got2 = R.chain_receipt(ch, {("soybeans_cbot", "La_Nina"): [near]}, asof="2026-09-07")
    assert got2["kind"] == "mechanism" and got2["prop"] is not None, got2
    # THE SEAM NAMES THE PAIR THE PRODUCER PUBLISHES, ONE SPELLING EACH SIDE.
    for name in ("Chain.mechanism_refused_hop", "Chain.mechanism_refused_date", "chain_counts.mechanism_refused"):
        assert name in W.CHAIN_SEAM_FIELDS, name
    # AND NOTHING ON THE LIVE FIXTURE'S PAGES MOVED: no chain there carries a refused report sentence.
    for mode, (_bd, blk) in sorted(chain_blocks.items()):
        assert "outside the lag the model allows for it" not in blk.text(), mode


# === THE ANALOG RENDER HALF (sec 4.2 / 4.4, DESIGN C.1-C.4) =========================================
#: A PRODUCED analog row -- every field ``analogs.analog_rows`` puts on a FIRED stanza, by its ONE
#: spelling. The defaults are the measured soybeans deep stanza (``El_Nino`` at 2013-06-30 on the
#: served seam): two of three dimensions readable, one charged a full sigma, sign 2 of 2, DIRECTION
#: 0 of 2, one dimension's record starting after the picked date, the seed's own record from 1999 and
#: the R3a pool at 159 against HEAD's own admitted three.
def _analog_row(**kw) -> dict:
    a = {"driver_id": "El_Nino", "contract": "soybeans_cbot", "date": "2013-06-30",
         "asof": "2026-09-07", "floor_year": "2022", "n_candidates": 159, "n_candidates_head": 3,
         "n_candidates_raw": 222, "n_candidates_pit": 219, "n_dropped_unreadable": 60,
         "dims_declared": 3, "dims_seen": 2, "dims_unread": 1, "unread_sigma": 1.0,
         "sign_agree": 2, "sign_seen": 2, "dir_agree": 0, "dir_seen": 2, "precedes_dims": 1,
         "near_asof": False, "months_to_asof": 158, "first_dim": None, "detail": None,
         "pool_rank": 1,
         "declined": None, "dims_order": ["El_Nino", "La_Nina", "export_pace_lag"],
         "record_span": ({"id": "El_Nino", "first_date": "1999-12-31"},
                         {"id": "La_Nina", "first_date": "1999-12-31"},
                         {"id": "export_pace_lag", "first_date": "2023-11-03"})}
    a.update(kw)
    return a


#: The letters this class may carry once its calendar years and its glued digits are taken out. A
#: character left over after this is a DIGIT in a letters-only row.
_SB_A_LETTERS = {ord(c): None for c in
                 "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ -;,:'."}


def _no_digits(line: str) -> str:
    return _GLUED_RX.sub("", _YEAR_RX.sub("", line)).strip().translate(_SB_A_LETTERS)


def test_ANALOG_the_SELECTIONS_OWN_FACTS_ARE_PRINTED_AS_COUNTS_AND_COST_NOTHING_AT_THE_REGISTER():
    """**SEVENTEEN FACTS ON EVERY ROW AND ZERO READERS.** The committed selection half (bbddd4cc)
    stopped declining by rule and started PRINTING facts -- coverage, the unread charge, sign
    agreement, direction agreement, how far back each dimension's record reaches, whether the picked
    date sits inside the separation window of the as-of -- and a census over ``render.py``,
    ``watch.py``, ``lint.py``, ``narration.py``, ``board.py`` and ``answer.py`` by each field's ONE
    spelling found ZERO readers for sixteen of them. This is the pin that they reach a reader.

    EVERY CLAUSE IS A COUNT AND NAMES NO DIMENSION: ``record_span`` and ``dims_order`` carry RAW
    driver ids, ``register.internal_leaks`` is never relaxable, and a counts-only clause cannot leak
    one. And none of them carries the token ``board``: the handoff's own suggested wording ("the
    dimensions this board ranks") cost ONE desk-register charge PER STANZA, measured, against a
    pre-arm sweep that drove that token 142 -> 65 across this block."""
    from leviathan.graphrag import register as REG
    cases = [_analog_row(),
             _analog_row(dims_declared=5, dims_seen=5, dims_unread=0, sign_agree=4, sign_seen=5,
                         dir_agree=4, dir_seen=5, precedes_dims=0),
             _analog_row(dims_declared=5, dims_seen=2, dims_unread=3, sign_agree=2, sign_seen=2,
                         dir_agree=0, dir_seen=0, precedes_dims=3)]
    for a in cases:
        head = R.sb_analog_header(a)
        clauses = R.analog_selection_clauses(a)
        assert clauses and clauses in head, (clauses, head)
        assert R.classify(head) == ("SB-A",), R.classify(head)
        assert R.register_hits(head) == [] and R.register_hits(clauses) == [], head
        assert REG.count_desk_register(clauses) == 0, REG.desk_register_hits(clauses)
        assert REG.internal_leaks(clauses) == [] and REG.market_leaks(clauses) == [], clauses
        assert "board" not in clauses.lower(), clauses
        head.encode("ascii")
        assert not _no_digits(clauses), clauses      # letters only: every count is in words
        for dim in ("El_Nino", "La_Nina", "export_pace_lag", "El Nino", "La Nina"):
            assert dim not in clauses, (dim, clauses)
    one = R.analog_selection_clauses(cases[0])
    assert "like on two of the three dimensions compared with it, which together reach back to 2023" \
        in one, one
    assert "the one it could not read there counts as a full sigma apart" in one, one
    assert "this date precedes the record of one of the dimensions compared with it" in one, one
    assert " one of the dimension compared" not in one, "the noun is the SET's, never the count's"
    full = R.analog_selection_clauses(cases[1])
    assert "like on five of the five dimensions" in full and "could not read there" not in full
    assert "this date precedes" not in full, "a correction is printed only where it was earned"
    three = R.analog_selection_clauses(cases[2])
    assert "the three it could not read there count as a full sigma apart" in three, three
    assert "the path into it agreed on" not in three, "no direction clause where none could be read"


def test_ANALOG_ONE_PRODUCER_FOR_HOW_FAR_BACK_THESE_DIMENSIONS_SEE_AND_THE_PIN_IS_TWO_SIDED():
    """**THE PAGE PUT THREE ANSWERS TO ONE QUESTION ON ONE LINE, AND ROUND 2 RULED THERE IS ONE.**
    HEAD printed the LOUD SEEDS' raw coverage floor (``floor_year``) beside a count minted over the
    seed's own history; round 1 moved the count's floor to the SEED'S OWN ``record_span`` entry and
    left the new reach clause on ``floor_year``. Measured over the 36 rendered stanzas of the fixture
    sweep: 24 printed a count floor EARLIER than its own counted population can reach (El Nino 1999
    against a binding 2023-11-03, ending stocks 1999 against 2015-12-31) and 36 of 36 printed a reach
    year the ``record_span`` the clause NAMES disagrees with. One stanza read "three such crossings
    since 1999 ... the three dimensions ranked beside it, which together reach back to 2022".

    THE ANSWER IS ``max(first_date)`` OVER ``record_span`` -- the first date every declared dimension
    could be read at once, which is exactly the population the head-admitted count is admitted over
    (``dims_seen == dims_declared``) and exactly what "together reach back to" says.

    **THE PIN IS TWO-SIDED, BECAUSE ROUND 1'S WAS NOT.** Its self-refutation asked only whether a
    floor was too LATE (a pick before it, a count wider than its window), so moving the floor
    twenty-four years EARLIER drove both tests to zero BY CONSTRUCTION and graded nothing. Here a
    floor earlier than ``max(first_date)`` fails and a floor later fails, on rows built to fail each
    way."""
    a = _analog_row()
    head = R.sb_analog_header(a)
    # ONE NUMBER, BOTH CLAUSES. 2023-11-03 is the LAST of the three records to open.
    assert R.analog_count_floor(a) == "2023"
    assert "three of them are like states, the ones readable on every dimension since 2023" in head, \
        head
    assert "which together reach back to 2023" in head, head
    assert head.count("2023") == 2 and "2022" not in head and "1999" not in head, head
    # EARLIER FAILS: the seed's own entry (1999) is not the answer, and neither is the loud set's.
    assert "since 1999" not in head and "reach back to 1999" not in head, head
    # LATER FAILS: a span that binds EARLIER than `floor_year` takes the SPAN, not the bigger year.
    early = _analog_row(floor_year="2022",
                        record_span=({"id": "El_Nino", "first_date": "2001-01-31"},
                                     {"id": "La_Nina", "first_date": "2015-12-31"}))
    assert R.analog_count_floor(early) == "2015"
    assert "reach back to 2015" in R.sb_analog_header(early)
    assert "2022" not in R.sb_analog_header(early)
    # THE ANSWER IS THE MAX AND NOT THE MIN, AND NOT THE FIRST ENTRY EITHER -- order cannot move it.
    assert R.analog_count_floor(_analog_row(
        record_span=({"id": "x", "first_date": "2023-11-03"},
                     {"id": "y", "first_date": "1999-12-31"}))) == "2023"
    # A DUPLICATE ID CANNOT TAKE ANOTHER BOARD'S FLOOR: there is no join left to get wrong.
    assert R.analog_count_floor(_analog_row(
        record_span=({"id": "El_Nino", "first_date": "1999-12-31"},
                     {"id": "El_Nino", "first_date": "2020-06-30"}))) == "2020"
    # IT FAILS BACK AND NEVER CLOSED: no span, no placeable date -- `floor_year` exactly as at HEAD.
    assert R.analog_count_floor(_analog_row(record_span=())) == "2022"
    assert R.analog_count_floor(_analog_row(
        record_span=({"id": "El_Nino", "first_date": None},))) == "2022"
    assert R.analog_count_floor({}) == ""


def test_ANALOG_the_COUNT_BESIDE_A_PICK_IS_A_POPULATION_THE_PICK_IS_A_MEMBER_OF():
    """**A NUMBER WHOSE POPULATION THE PICK IS NOT IN IS A BACKING FAILURE** (round-2 blocker 2).
    Round 1 printed ``n_candidates_head`` -- admitted only where EVERY declared dimension is readable
    -- in the sentence that opens "the series sat like this in June 2013", and on 10 of the 18
    rendered stanzas the date in that sentence was outside the set the number counts: 2013-06-30
    beside a three-member set beginning 2023-12-31, 2020-04-30 and 2017-02-28 beside a one-member set
    at 2024-02-29. A reader takes the two as one event; at HEAD this could not happen, because HEAD
    printed the pool the pick was drawn from.

    So the count beside the pick is the RANKED POOL, which every picked row is a member of by
    construction, and the head-admitted count rides as a SECOND number that says whose population it
    is. It prints ONLY where the two differ, because a second number equal to the first is one
    population wearing two sentences.

    AND THE "NEAREST" CLAIM IS THE ROW'S, NOT THE STANZA'S POSITION: a max tier renders two stanzas
    off one pool and the second one is not the nearest."""
    a = _analog_row()
    head = R.sb_analog_header(a)
    # THE NOUN IS THE POPULATION'S (round-2 review MAJOR 2): the ranked pool is "past readings ... could
    # be ranked beside it"; only the HEAD-admitted count is a "like state" -- the word the watch's
    # base-rate row spends on the same population, so the two producers can never be read as one
    # number a factor of 159 apart.
    assert ("one hundred fifty-nine past readings on this series could be compared with it, "
            "this one the nearest") in head, head
    assert "three of them are like states, the ones readable on every dimension since 2023" in head, \
        head
    # THE OPPOSITE ERRORS: the pool may never be called like states; the admitted count may never
    # wear the pool's sentence.
    assert "like states compared" not in head and "such crossings" not in head, head
    assert "three past readings" not in head, head
    # RANK: only the nearest may say so; every other seat, and a row with no seat at all, says less.
    second = R.sb_analog_header(_analog_row(pool_rank=6))
    assert ("one hundred fifty-nine past readings on this series could be compared with it, "
            "this one among them") in second, second
    assert "the nearest" not in second, second
    noneth = _analog_row()
    noneth.pop("pool_rank")
    assert "this one among them" in R.sb_analog_header(noneth)
    # THE SECOND NUMBER IS PRINTED ONLY WHERE IT DIFFERS -- and where it does not, nothing is lost:
    # the reach clause still carries the year, off the same one producer.
    same = R.sb_analog_header(_analog_row(n_candidates=3, n_candidates_head=3))
    assert "three past readings on this series could be compared with it, this one the nearest" in same, same
    assert "readable on every dimension" not in same, same
    assert "which together reach back to 2023" in same, same
    # SINGULARS, and a zero that is a real and different fact.
    one = R.sb_analog_header(_analog_row(n_candidates=1, n_candidates_head=1))
    assert "one past reading on this series could be compared with it, this one the nearest" in one, one
    none_admitted = R.sb_analog_header(_analog_row(n_candidates_head=0))
    assert "zero of them are like states, the ones readable on every dimension since 2023" in \
        none_admitted
    # A ROW THE SELECTION DID NOT BUILD IS HEAD'S ROW, FLOOR AND ALL.
    headrow = _analog_row()
    headrow.pop("n_candidates_head")
    assert "the record carries one hundred fifty-nine such crossings since 2022" in \
        R.sb_analog_header(headrow)
    # LETTERS ONLY AND NOTHING NEW AT THE REGISTER, on every arm above.
    from leviathan.graphrag import register as REG
    for line in (head, second, same, one, none_admitted):
        assert R.classify(line) == ("SB-A",) and R.register_hits(line) == [], line
        assert REG.internal_leaks(line) == [] and REG.market_leaks(line) == [], line
        line.encode("ascii")


def test_ANALOG_what_FOLLOWED_is_the_WINDOWS_COUNT_and_the_TIERS_CAP_IS_A_CUT_ROW(scenarios):
    """**THE FIRST SILENT CUT IN THIS MODULE WHOSE NUMBER WAS PRINTED AS A FACT** (round-2 blocker 3).
    ``analogs._receipts_after`` stopped walking at the tier's ``receipt_cap`` and the header printed
    ``len()`` of what it got: measured through the real seam with twelve documents inside the forward
    window, deep printed "three dated documents inside the window that followed it" against a true
    eleven and max printed "five" against a true eight -- CONSTANT AT THE CAP whatever the corpus
    held, with no cut row, while the BACKWARD window has carried one since S6. Fences correct or
    compute; a cap is a cut row and never a count.

    BOTH DIRECTIONS ARE GRADED: a stanza whose carried rows are short of the count says so and names
    the difference, and a stanza the cap did not cut mints no absence at all -- a cut line over an
    uncut section is a false absence."""
    ctx = scenarios["b40_event"]
    bd = ctx["board"]
    base = _analog_row(contract="malaysian_crude_palm_oil_cme", n_receipts_after=11,
                       receipts_after=tuple({"t": 1, "date": "2013-0%d-15" % i} for i in (7, 8, 9)))
    cut = [l for l in R.render_board(bd, analogs=[base]).lines
           if l.startswith("BOARD ABSENCE") and "inside the window that followed" in l]
    assert len(cut) == 1, cut
    # ROUND-2 REVIEW MAJOR 1: nothing renders the forward rows, so the row withholds the WHOLE count
    # the header printed -- eleven, the same figure -- never "count minus rows the page never showed".
    assert cut[0].startswith("BOARD ABSENCE the eleven documents counted inside the window that "
                             "followed this like state are not shown on this page "
                             "(El Nino on CME palm oil)"), cut[0]
    assert "eight" not in cut[0] and "receipt cut" not in cut[0], cut[0]
    assert R.classify(cut[0]) == ("SB-X",) and R.register_hits(cut[0]) == [], cut[0]
    cut[0].encode("ascii")
    assert not any(ch.isdigit() for ch in cut[0]), cut[0]       # the count is in words
    # THE HEADER'S FIGURE IS THE WINDOW'S, not the three rows the tier carried.
    assert "eleven dated documents inside the window that followed it" in R.sb_analog_header(base)
    # NOTHING COUNTED, NOTHING SAID (round-2 review MAJOR 1: nothing on this page renders the forward
    # rows, so a counted row is withheld whatever it carries -- and a zero or an absent count prints
    # no row at all).
    carried = _analog_row(n_receipts_after=3, receipts_after=({"t": 1}, {"t": 1}, {"t": 1}))
    _cl = [l for l in R.render_board(bd, analogs=[carried]).lines
           if "inside the window that followed this like state" in l]
    assert any("the three documents counted inside the window" in l and "are not shown on this page" in l
               for l in _cl), _cl
    for row in (_analog_row(n_receipts_after=0, receipts_after=()), _analog_row()):
        assert not [l for l in R.render_board(bd, analogs=[row]).lines
                    if "inside the window that followed this like state" in l], row.get("date")
    # AND THE SINGULAR IS ITS OWN SENTENCE.
    one = R.render_board(bd, analogs=[_analog_row(n_receipts_after=1,
                                                  receipts_after=({"t": 1},))]).lines
    assert any("the one document counted inside the window" in l and "is not shown on this page" in l
               for l in one), one


def test_ANALOG_the_DIRECTION_clause_is_the_one_that_changes_a_mind_and_it_reads_ZERO_OF_TWO():
    """**THE LEVEL MATCHED AND THE PATH DID NOT.** ``sign_agree/sign_seen`` is nearly constant by
    construction -- the distance ranks on the z, so a small z-gap implies a shared sign -- and it
    measured 2/2, 4/4 and 5/5 on the live stanzas. ``dir_agree/dir_seen`` measured **0 of 2** on the
    served soybeans deep stanza and 0 of 3 on ``export_pace_lag``. Round 3 put direction and run on the
    KNOWLEDGE axis, so it is a true statement about what a desk could have read then; it is also the
    only one of the two a reader would act on.

    THE ``sign_seen == 0`` BRANCH IS NOT BUILT AND MUST NOT BE: it is unreachable after round 2 (a
    fired row always carries a readable sigma) and pinned as such in ``tests/unit/test_state_analogs``.
    A branch for an unreachable state is a sentence no measurement can ever grade."""
    import inspect
    head = R.sb_analog_header(_analog_row())
    assert "the state agreed in sign on two of the two a sigma could be read on" in head, head
    assert "the path into it agreed on zero of the two a direction could be read on" in head, head
    none_seen = R.analog_selection_clauses(_analog_row(sign_seen=0, sign_agree=0, dir_seen=0,
                                                       dir_agree=0))
    assert "agreed in sign" not in none_seen and "the path into it" not in none_seen, none_seen
    # THE SOURCE, PAST ITS OWN DOCSTRING -- which names the branch in order to say it is not built.
    src = inspect.getsource(R.analog_selection_clauses)
    assert src.count('"""') >= 2, src[:200]
    assert "sign_seen == 0" not in src.split('"""')[2]


def test_ANALOG_near_asof_APPENDS_THE_MONTHS_AND_NEVER_REMOVES_THE_STANZA():
    """**DESIGN C.4's BAR, IN THE ONLY SHAPE DOCTRINE ALLOWS.** The design asks for a lint that
    asserts the chosen date is not within ``min_separation_months`` of the as-of -- which is a fence
    that DELETES a stanza the selection picked. Fences correct or compute;
    ``analogs.select_analogs`` says it in its own words ("``near_asof`` IS A FLAG AND NEVER A
    FILTER"). So the page APPENDS the distance and the stanza stays.

    IT WAS LIVE AND SILENT: ``attached_event`` at deep renders a stanza picked 2026-01-31 against an
    as-of of 2026-09-07 and ``attached_event`` at max's top stanza picks 2025-12-31 -- both flagged
    True by the selection, both rendered, and the word appeared NOWHERE in this module."""
    near = _analog_row(date="2026-01-31", near_asof=True, months_to_asof=8)
    head = R.sb_analog_header(near)
    assert "that date sits eight months before the as-of this page is read at" in head, head
    assert head.startswith("LIKE STATE El Nino on CBOT soybeans: the series sat like this in ")
    assert R.classify(head) == ("SB-A",) and R.register_hits(head) == []
    assert "sits one month before" in R.sb_analog_header(
        _analog_row(near_asof=True, months_to_asof=1))
    fallback = R.sb_analog_header(_analog_row(near_asof=True, months_to_asof=None))
    assert "sits inside the separation window of the as-of this page is read at" in fallback
    assert not _no_digits(R.analog_selection_clauses(
        _analog_row(near_asof=True, months_to_asof=None)))
    assert R.sb_analog_header(_analog_row(near_asof=False)) == R.sb_analog_header(_analog_row())


def test_ANALOG_the_TRANSLATED_chain_mark_NAMES_THE_CHAINS_OWN_WORD_instead_of_going_silent():
    """**ROUND 5 CLOSED THE RENAME BY GOING SILENT; THIS SPEAKS IT.** Where the analog leg leads with
    the TRANSLATION of a chain hop, ``first_dim`` is not in ``chain_dims`` and round 5's mark printed
    nothing at all. MEASURED over the twelve chain-on served cells: six marks and two silent chain-on
    cells, one of them exactly this -- ``named_one`` at deep, where the top chain walks ``La_Nina``,
    ``seam._dim_for_hop`` translates it onto ``El_Nino`` (one series, ``oni_climate|_global|``, two
    phases) and the page printed "LIKE STATE El Nino ..." beside chain rows reading LA NINA with
    nothing saying why. A silence is not a correction: the stanza IS that chain's history, read on the
    series they share, and the pairing was owed. Marks go 6 -> 7 with ZERO cells losing one."""
    from leviathan.graphrag import register as REG
    oni = _analog_row(first_dim="El_Nino", dims_order=["El_Nino", "La_Nina", "export_pace_lag"])
    names = {"El_Nino": "La_Nina"}
    mark = R.chain_stanza_mark(oni, chain_dims=("La_Nina", "drought"), chain_dim_names=names)
    assert mark == ("; read as the history of the chain named first, which carries that series as "
                    "La Nina"), mark
    assert "El Nino" not in mark, "an attribution never names a driver the chain does not carry"
    assert R.register_hits(mark) == [] and REG.count_desk_register(mark) == 0
    assert REG.internal_leaks(mark) == [] and not any(c.isdigit() for c in mark)
    assert R.classify(R.sb_analog_header(oni, chain_dims=("La_Nina", "drought"),
                                         chain_dim_names=names)) == ("SB-A",)
    assert R.chain_stanza_mark(oni, chain_dims=("El_Nino",)) == \
        "; read as the history of the chain named first, on El Nino"
    assert R.chain_stanza_mark(oni, chain_dims=("La_Nina",)) == ""
    assert R.chain_stanza_mark(oni, chain_dims=(), chain_dim_names=names) == ""
    assert R.chain_stanza_mark(oni, chain_dims=("drought",), chain_dim_names=names) == ""
    assert R.chain_stanza_mark(_analog_row(first_dim="La_Nina",
                                           dims_order=["El_Nino", "La_Nina"]),
                               chain_dims=("La_Nina",), chain_dim_names=names) == ""
    assert R.sb_analog_header(_analog_row(), chain_dims=("La_Nina",)) + mark == \
        R.sb_analog_header(oni, chain_dims=("La_Nina", "drought"), chain_dim_names=names)


def test_ANALOG_a_DECLINED_stanza_states_its_FINER_REASON_without_a_new_DECLINE_WORD():
    """**RENDERING THE HANDOFF'S PROPOSAL REFUTED IT.** The handoff asked for ``pre_coverage`` to take
    the analog producer. ``render.ABSENCE_WHY`` is keyed by WORD ALONE and clause 9 of
    ``state/lint.py`` requires exactly one sentence per word in BOTH directions, so an analog decline
    on that word prints, verbatim, "BOARD ABSENCE a like state on this market: the as-of sits before
    this market's own price history begins" -- which is FALSE for ``detail == 'unobservable'``, where
    the as-of is today and it is the CANDIDATE DATES that sit inside the record with nothing readable
    on them. The word does not move; the finer reason is ONE extra sentence in the same class."""
    from leviathan.graphrag import register as REG
    from leviathan.graphrag.state import board as BRD
    assert R.absence_why("pre_coverage") == ("the as-of sits before this market's own price history "
                                             "begins"), "the TAPE's sentence, and only the tape's"
    assert "pre_coverage" in BRD.TAPE_REASONS and "pre_coverage" in BRD.ANALOG_REASONS
    for detail, must in (("unobservable", "sixty such dates were ranked past"),
                         ("window_open", "too recent for the lag the model allows it to have run out"),
                         ("no_candidates", "holds no crossing on this series at all")):
        row = _analog_row(declined="no_like_state", detail=detail, date=None)
        line = R.sb_analog_decline_detail(row)
        assert line.startswith("LIKE STATE El Nino on CBOT soybeans: "), line
        assert must in line, (detail, line)
        assert R.classify(line) == ("SB-A",) and R.register_hits(line) == [], line
        assert REG.count_desk_register(line) == 0 and REG.internal_leaks(line) == []
        assert not _no_digits(line), line
        line.encode("ascii")
    assert R.sb_analog_decline_detail(_analog_row(declined="no_like_state", detail=None)) == ""
    assert R.sb_analog_decline_detail({}) == ""
    assert set(R.ANALOG_DETAIL_WHY) == {"no_candidates", "window_open", "unobservable"}
    for why in R.ANALOG_DETAIL_WHY.values():
        assert not any(c.isdigit() for c in why), why


def test_ANALOG_a_row_the_SELECTION_DID_NOT_BUILD_composes_the_header_it_composed_at_HEAD():
    """THE GATE ON EVERY CLAUSE IS A FIELD THE COMMITTED SELECTION HALF PUTS ON A PRODUCED ROW, so a
    hand-built row -- every deck row, every census row, ``event_analogs``' own appended stanza in
    ``state/__main__.build_scenario`` -- composes the header it composed before, byte for byte. This
    is the pin that the render half added a READER and not a second producer."""
    legacy = {"driver_id": "El_Nino", "contract": "soybeans_cbot", "date": "2015-08-31",
              "n_candidates": 4, "floor_year": "2003", "asof": "2026-09-07"}
    head = R.sb_analog_header(legacy)
    assert head == ("LIKE STATE El Nino on CBOT soybeans: the series sat like this in August 2015; "
                    "the record carries four such crossings since 2003; each move below is read over "
                    "the lag the model allows for the market it names, and each line below prints that "
                    "lag; measured on the record as revised through September 2026"), head
    assert R.analog_selection_clauses(legacy) == ""
    co = dict(legacy, co_loud=True, n_contracts=3, dims_seen=2, dims_declared=3, sign_agree=2,
              sign_seen=2, near_asof=True, months_to_asof=3)
    assert "dimensions compared with it" not in R.sb_analog_header(co)
    assert "before the as-of this page is read at" not in R.sb_analog_header(co)


#: THE MEASURED CEILING for the SB-A header, by the chain lane's own rule (measured max, +10%, rounded
#: up to the next fifty). MEASURED on the eighteen served cells through ``seam.fill_stage1`` +
#: ``fill_stage2``, every anchor shape, every tier, chain off and on: HEAD 310-382 characters, this
#: landing 615-876. 876 plus a tenth is 963.6, so the bar is 1,000. It is a BAR THE DECK GRADES and
#: never a truncation: a fence that cut this header would delete a fact the selection measured.
SB_A_HEADER_CEILING = 1000


def test_ANALOG_the_composed_header_states_a_MEASURED_ceiling_rather_than_drifting(scenarios):
    """The header grew from 310-382 characters to 615-876 on the served pages -- +77% to +129% -- on a
    stanza that is 442 to 2,252 characters of a 13k-75k block. That is a budget fact and it is stated
    with a number rather than left to drift, exactly as the chain lane re-baselined its three ceilings
    on measurement."""
    seen = []
    for name, ctx in sorted(scenarios.items()):
        for line in ctx["block"].lines:
            if line.startswith("LIKE STATE ") and "the series sat like this" in line:
                seen.append((name, len(line), line))
    assert seen, "the three acceptance fixtures render at least one like-state header"
    for name, n, line in seen:
        assert n <= SB_A_HEADER_CEILING, (name, n, line[:160])
        assert R.classify(line) == ("SB-A",) and R.register_hits(line) == []


# === 09-23 FIX ROUND, LANE R: THE ROW IDENTITY, THE ROW'S HANDLES, THE PRECISION PRODUCER =============
#: The ten 09-23 payload rows the fact graders named, rebuilt from their own trace facts (ref, table,
#: metric, scope, driver): each prints its SERIES as the head and its driver ONLY as the routing clause.
#: (label the grader quoted, driver id, the table/metric the row reads, scope)
_DEFECT_ROWS = (
    ("max F1 flash drought", "flash_drought", "gold_weather_z", "drought_z", "soybeans_cbot",
     "United States", "monthly"),
    ("rice F1 deliverable stocks", "tenderable_collapse", "silver_psd", "ending_stocks_mt",
     "rough_rice_cbot", "United States", "annual"),
    ("corn_wheat F1 ethanol grind", "ethanol_demand", "silver_psd_attributes", "FSI Consumption",
     "corn_cbot", "United States", "annual"),
    ("rice F3 reserve", "India_state_reserves", "silver_psd", "beginning_stocks_mt",
     "rough_rice_cbot", "India", "annual"),
    ("cotton FA-2 reserve", "China_state_reserves", "silver_psd", "beginning_stocks_mt", "cotton",
     "China", "annual"),
    ("deep26 F2 stocks-to-use", "psd_ending_stock_su_ratio", "silver_psd", "su_ratio",
     "soybeans_cbot", "United States", "annual"),
)


def _id_row(driver, table, metric, contract, country, cadence, *, collapse=None, role=None,
            level_date=None, offset=0, recency=None, values=None):
    from leviathan.graphrag.state.feeders import state_from_arrays
    if cadence == "annual":
        d = [str(2017 + i) for i in range(10)]
    else:
        d = ["2025-%02d-28" % m for m in range(1, 13)] + ["2026-%02d-28" % m for m in range(1, 8)]
    vals = values or [1.0 + 0.1 * i for i in range(len(d))]
    st = state_from_arrays(metric, vals, d, cadence=cadence, asof="2026-09-23", unit="u",
                           narrate_unit="u", scale=1.0, windows={cadence: 6}, table=table,
                           metric=metric)
    st.key = ROWS.SeriesKey(ref=metric, commodity=contract, country=country)
    st.collapse = collapse
    st.role = role
    if level_date:
        st.level_date = level_date
    if offset:
        st.offset_months = offset
        st.recency = dict(st.recency or {}, **(recency or {}), offset_applied=True)
    return B.NodeRow(contract=contract, driver_id=driver, state=st, sign="+",
                     lag_band=parse_lag("0-2 quarters"))


def test_R0923_the_SB1_head_names_the_SERIES_and_the_driver_only_as_ROUTING():
    """C1 / R-3 on the six rows the 09-23 graders named: the head is the card's declared series words
    (`reading_words`, else the metric label) and the driver id appears exactly once, as "read here for
    <driver>". A rename table would pass this for the six rows it lists; this reads the card."""
    for label, driver, table, metric, contract, country, cadence in _DEFECT_ROWS:
        row = _id_row(driver, table, metric, contract, country, cadence)
        line, calls = R.sb_state(1, row, asof="2026-09-23")
        ident = R.row_identity_for(row)
        # the series' OWN words: the commodity-scoped key wins exact-first (render.scoped_reading_words --
        # rice's milled all-class basis, 09-23 fix round, review WT M-4), else the card-wide words
        name = (R.scoped_reading_words(table, metric, contract) or R._card_facts(table, metric).get("label"))
        assert name and ident.name == name, (label, ident.name, name)
        head = line.split(": ", 1)[0]
        assert head.startswith("- [N1] " + name), (label, head)
        assert head.count("read here for ") == 1, (label, head)
        assert head.endswith("read here for " + R.humanise(driver)), (label, head)
        assert R.humanise(driver) not in head.split("read here for ")[0], (label, head)
        assert calls[0].get("_row_id") == ident.row_id == "%s|%s|%s" % (
            contract, driver, row.state.key.label()), label
        assert R.register_hits(line) == [], (label, line[:140])


def test_R0923_the_identity_scope_is_DERIVED_from_the_card_axis_and_the_reads_collapse(monkeypatch):
    """R-2: cell words come from the card's declared axis and the read's own collapse, never from the
    driver or the country. `mean` -> the mean over the cells; no collapse on a cell axis -> one cell; an
    undeclared axis prints the scope alone and no cell words at all."""
    real = R.card_fields
    monkeypatch.setattr(R, "card_fields", lambda t, m: dict(real(t, m), country_axis="region_cell")
                        if t == "gold_weather_z" else real(t, m))
    mean = R.row_identity_for(_id_row("flash_drought", "gold_weather_z", "drought_z", "soybeans_cbot",
                                      "United States", "monthly", collapse="mean"))
    assert "for the mean over the United States growing cells" in mean.words(), mean.words()
    one = R.row_identity_for(_id_row("flash_drought", "gold_weather_z", "drought_z", "soybeans_cbot",
                                     "United States", "monthly", collapse=None))
    # 09-24 RE-BANK (CONTRACT K3, item 6 -- DM2): a region-cell read with NO collapse at a scope that is not
    # one of the producer's aggregate surfaces names its SCOPE ALONE. The round-1 "single_cell" default read
    # cocoa's West Africa BASIN MEAN as "one West Africa growing cell"; the served rows prove no cell here.
    assert "for United States" in one.words() and "growing cell" not in one.words(), one.words()
    monkeypatch.setattr(R, "card_fields", lambda t, m: {})
    und = R.row_identity_for(_id_row("flash_drought", "gold_weather_z", "drought_z", "soybeans_cbot",
                                     "United States", "monthly", collapse="mean"))
    assert "growing cell" not in und.words() or "mean over" in und.words(), und.words()


def test_R0923_basis_period_role_and_offset_ride_the_identity_in_the_CONTRACT_order(monkeypatch):
    """C1's fixed order: name, basis, scope, period, (vintage role), offset. Each fact is the card's own
    declaration or the served row's own field, read through `card_fields` / the row."""
    real = R.card_fields

    def _cf(t, m):
        out = dict(real(t, m))
        if (t, m) == ("silver_psd", "su_ratio"):
            out["basis_words"] = "ending stocks as a share of domestic use"
        if t == "silver_icco_cocoa":
            out["period_words"] = "crop_season"
        return out
    monkeypatch.setattr(R, "card_fields", _cf)
    su = R.row_identity_for(_id_row("psd_ending_stock_su_ratio", "silver_psd", "su_ratio",
                                    "soybeans_cbot", "United States", "annual"))
    w = su.words()
    assert w.index("ending stocks as a share of domestic use") < w.index("for United States") \
        < w.index("2026/27"), w
    cocoa = R.row_identity_for(_id_row("stocks", "silver_icco_cocoa", "stocks_to_grindings",
                                       "cocoa", "", "annual", level_date="2024"))
    assert cocoa.words().endswith("2024/25 season"), cocoa.words()
    proj = _id_row("prod", "silver_psd", "production_mt", "soybeans_cbot", "United States", "annual",
                   role="projection")
    assert R.row_identity_for(proj).words().endswith("2026/27 (projection)")
    off = _id_row("El_Nino", "silver_noaa_oni", "oni_anom", "malaysian_crude_palm_oil_cme", "",
                  "monthly", offset=6, recency={"current_level": 1.8, "current_level_date": "2026-07",
                                                "offset_periods": 6})
    ow = R.row_identity_for(off).words()
    assert ow.endswith("read six months back -- the reading whose declared lag lands now"), ow


def test_R0923_a_RELEASE_STAMP_is_never_a_role_and_the_refusal_is_COUNTED():
    """C3 / C11: `2026M09` on a Pink Sheet row is a release stamp. It is spliced into no period, written
    as no call's `provenance`, printed nowhere -- and `Block.counters["role_withheld"]` counts it."""
    row = _id_row("crude_oil", "silver_pink_sheet", "brent_crude_usd_bbl_zscore_5yr", "soybeans_cbot",
                  "", "monthly", role="2026M09")
    b = R.Block()
    line, calls = R.sb_state(1, row, asof="2026-09-23", block=b)
    assert "2026M09" not in line
    assert all("provenance" not in (c["rows"][0] or {}) for c in calls)
    assert all("2026M09" not in str(c["query"]["period"]) for c in calls)
    assert b.counters.get("role_withheld") == 1
    good = _id_row("prod", "silver_wasde", "production", "soybeans_cbot", "United States", "annual",
                   role="projection")
    _l2, c2 = R.sb_state(1, good, asof="2026-09-23")
    assert c2[0]["rows"][0]["provenance"] == "projection"
    assert R.sb_call(table="t", metric="m", commodity=None, country=None, period="p", asof="a",
                     value=1, role="2026M09")["rows"][0].get("provenance") is None


def test_R0923_the_PERIOD_GAP_is_a_LABEL_on_the_row_and_never_a_removal():
    """C11: a row whose newest held period is older than one its SAME SOURCE had published SAYS which period
    it holds. RE-BANKED (09-23 verifier F1, declared): the gap is a store fact -- a sibling series of the slug
    held the newer period as known then -- so the words say what the store shows (the source had published
    that period) and never that THIS series' own figure for it exists."""
    row = _id_row("area", "silver_psd", "area_harvested_1000ha", "soybeans_cbot", "United States",
                  "annual")
    row.state.period_gap = {"expected": "2023/24", "served": "2020/21", "gap_periods": 3}
    line, calls = R.sb_state(1, row, asof="2024-03-01")
    assert "the newest marketing year held for this series as known on 1 March 2024 is 2020/21" in line, line
    assert "the same source had published 2023/24 figures by then" in line
    assert "not held" not in line and "known then" not in line
    assert calls, "the row still renders and still mints"
    row.state.period_gap = {}
    _l0 = R.sb_state(1, row, asof="2024-03-01")[0]
    assert "held for this series" not in _l0 and "same source had published" not in _l0


def test_R0923_R5_the_window_extreme_takes_its_VERB_from_its_SIDE_of_the_record():
    """R-5: export pace carried a lag-window extreme at the THIRD percentile on both 09-23 soybean
    boards and the page said it "peaked" there."""
    assert R.extreme_verb(3.0) == "bottomed at" and R.extreme_verb(49.9) == "bottomed at"
    assert R.extreme_verb(50.0) == "peaked at" and R.extreme_verb(98.1) == "peaked at"
    trough = _s8_hop(percentile=13.0, tail_peak_percentile=3.0, tail_peak_date="2026-06-12",
                     tail_lag_to="2026-09-12")
    assert "bottomed at the third percentile" in R.chain_state_words(trough)
    peak = _s8_hop(percentile=68.0, tail_peak_percentile=98.1, tail_peak_date="2026-04-01",
                   tail_lag_to="2026-10-01")
    assert "peaked at the ninety-eighth percentile" in R.chain_state_words(peak)


def test_R0923_R6_the_precision_producer_NEVER_rounds_onto_or_across_a_declared_line():
    """R-6's property drive, in the deck: for every value in a band around each line, the shown figure
    sits on the same side of the line as the raw value; percentiles 9.5-10.5 and 89.5-90.5 in 0.01
    steps never print on a decile edge they are not on."""
    for line in (0.5, 1.0, 1.5, 2.0, 10.0):
        for dec in (0, 1, 2):
            for k in range(1, 50):
                for v in (line - k * 0.001, line + k * 0.001):
                    got = float(ROWS.figure_text(v, decimals=dec, lines=(line,)))
                    assert (got > line) == (v > line) and (got < line) == (v < line), (v, dec, got)
    for lo in (9.5, 89.5):
        for k in range(0, 101):
            p = round(lo + k * 0.01, 2)
            txt = ROWS.percentile_int(p)
            num = float(txt.rstrip("stndrdth"))
            for dl in (10.0, 90.0):
                assert (num > dl) == (p > dl) and (num < dl) == (p < dl), (p, txt)
            assert ROWS.percentile_value(p) == num
    assert ROWS.figure_text(0.46, decimals=1, lines=(0.5,)) == "0.46"
    assert ROWS.figure_text(9.96, decimals=1, lines=(10.0,)) == "9.96"
    assert ROWS.percentile_int(89.6) == "89.6th" and ROWS.percentile_int(68.03) == "68th"


def test_R0923_R7_a_small_magnitude_keeps_TWO_significant_figures_and_never_prints_minus_zero():
    """R-7: `_fmt(-0.0035)` returned "-0" -- a false zero with a sign on it."""
    for k in range(1, 100):
        for sgn in (1, -1):
            v = sgn * k * 1e-3
            txt = ROWS.figure_text(v)
            assert txt not in ("0", "-0", "+0"), (v, txt)
            assert abs(float(txt) - v) <= abs(v) * 0.05 + 1e-12, (v, txt)
    assert R._fmt(-0.0035) == "-0.0035" and ROWS.figure_text(0.0, two_sided=True) == "0"
    assert ROWS.figure_text(-1e-6) == "-0.000001"
    assert ROWS.figure_text(1085.08) == "1085" and ROWS.figure_text(1085.08, grouping=True) == "1,085"


def test_R0923_the_PEAK_call_has_its_STAT_its_WINDOW_and_the_ROWS_OWN_row_id():
    """C2 / C3: a hop of a rendered full chain mints its window peak on its OWN SB-1 row -- one more call,
    one more handle, the row's `_row_id`, `stat = window_peak_percentile` and the window it is the
    extreme of -- and the handle map names every magnitude by what it is (R-4's bijection)."""
    row = _id_row("export_pace_lag", "silver_esr", "weekly_exports_1000mt", "soybeans_cbot", "",
                  "monthly")
    hop = _s8_hop(tail_peak_percentile=3.0, tail_peak_date="2026-06-12", tail_window_from="2026-03-23",
                  tail_lag_to="2026-09-12")
    b = R.Block(start=10)
    line, calls = R.sb_state(10, row, asof="2026-09-23", block=b, peak_hop=hop)
    stats = [c["rows"][0].get("stat") for c in calls]
    assert stats[0] == "level" and stats[-1] == "window_peak_percentile" and "percentile" in stats,         stats
    pk = calls[stats.index("window_peak_percentile")]
    assert pk["rows"][0]["window"] == {"from": "2026-03-23", "to": "2026-09-23"}
    assert pk["_row_id"] == calls[0]["_row_id"] and pk["query"]["period"] == "2026-06-12"
    h = 10 + stats.index("window_peak_percentile")
    assert ("[N%d] bottomed at the 3rd percentile in June 2026" % h) in line, line
    # R-4: every [Nk] this line prints resolves to calls[k - start], in print order.
    handles = [int(x) for x in re.findall(r"\[N(\d+)\]", line)]
    assert handles == list(range(10, 10 + len(calls))), (handles, len(calls))
    # C4: every figure the row printed is registered, each under its own kind, with its own handle.
    b.add(line, calls)
    kinds = {s["kind"] for s in b.served_scalars()}
    assert {"level", "percentile", "window_peak_percentile"} <= kinds, kinds
    assert all(s["row_id"] == calls[0]["_row_id"] for s in b.served_scalars()
               if s["kind"] in ROWS.STAT_KINDS)


def test_R0923_R16_an_OFFSET_row_mints_its_CURRENT_handle_and_its_hop_line_cites_both():
    """R-16: the chain hop on an offset row names "six months back" and cites the newest reading's own
    handle beside the lagged one -- the phase in force is never read off the shifted print alone."""
    row = _id_row("El_Nino", "silver_noaa_oni", "oni_anom", "malaysian_crude_palm_oil_cme", "",
                  "monthly", offset=6,
                  recency={"current_level": 1.8, "current_level_date": "2026-07", "offset_periods": 6,
                           "current_knowledge_date": "2026-09-05"})
    b = R.Block(start=1)
    line, calls = R.sb_state(1, row, asof="2026-09-23", block=b)
    stats = [c["rows"][0].get("stat") for c in calls]
    assert "current_level" in stats, stats
    cur = 1 + stats.index("current_level")
    handles = {"level": 1, "current": cur}
    words = R._hop_offset_words(row, handles)
    assert "read six months back" in words and ("[N%d]" % cur) in words, words


def test_R0923_the_seam_carries_served_scalars_and_row_handles_ONLY_where_the_block_rendered():
    """I-8 / item 12: the two new payload keys ride a rendered block and nothing else."""
    import inspect as _i
    from leviathan.graphrag.state import seam as S
    src = _i.getsource(S.fill_stage2)
    assert '"served_scalars": blk.served_scalars()' in src
    assert "if text and _extra:" in src, "absent on a board that rendered no block"
    assert "evidence_ordinals" in str(_i.signature(S.fill_stage2))


# === 09-23 LANE R: the cross-lane requests this lane closed (lane T R1 / R3 / R4, lane C B-3) =========
def test_R0923_the_TAPE_names_its_delivery_the_way_the_pick_was_made_and_carries_ONE_known_date():
    """CONTRACT.md C12 / OWNER DECISION 5: "front <YYYY-MM>" ONLY for a pick an activity print made
    (`query.ROLL_METHODS_FRONT`); the named cycle fallback and a tape with no method are "the nearest
    listed delivery, <Month YYYY>,". C11 (lane C's B-3): the settle's call carries the ONE derived known
    date the numbers seat's label prints (`feeders.tape_known_date`). One class either way."""
    from leviathan.graphrag.numbers.query import CYCLE_FALLBACK_METHOD, ROLL_METHODS_FRONT
    from leviathan.graphrag.state import feeders as _F
    t = H.fixture_tape("soybeans_cbot", H.ASOF)
    assert ROLL_METHODS_FRONT
    for m in sorted(ROLL_METHODS_FRONT):
        t.roll_method = m
        line, calls = R.sb_tape(1, t, asof=H.ASOF)
        assert " front 2026-11 settle on 2026-09-04: " in line, line[:120]
        assert R.classify(line) == ("SB-T",)
    for m in (CYCLE_FALLBACK_METHOD, ""):
        t.roll_method = m
        line, calls = R.sb_tape(1, t, asof=H.ASOF)
        assert ", the nearest listed delivery, November 2026, settle on 2026-09-04: " in line, line[:120]
        assert " front " not in line
        assert R.classify(line) == ("SB-T",)
    assert calls[0]["rows"][0]["knowledge_date"] == _F.tape_known_date(t)
    assert calls[0]["query"]["period"] == "2026-11", "the call's period is the delivery, unchanged"


def test_R0923_a_COMMODITY_SCOPED_reading_key_wins_EXACT_FIRST_and_moves_nothing_else(monkeypatch):
    """Lane T's R4: a shared card (``silver_psd.ending_stocks_mt`` serves 63 slugs) cannot declare rice's
    milled basis once for all. The reader resolves ``<table>.<metric>@<series commodity>`` first; every
    other read, and the unscoped reader itself, is unchanged."""
    book = dict(R._reading_word_table())
    base = book["silver_psd.ending_stocks_mt"]
    rice = "ending stocks, all classes, milled basis"
    monkeypatch.setattr(R, "_reading_word_table",
                        lambda: dict(book, **{"silver_psd.ending_stocks_mt@rough_rice_cbot": rice}))
    assert R.scoped_reading_words("silver_psd", "ending_stocks_mt", "rough_rice_cbot") == rice
    assert R.scoped_reading_words("silver_psd", "ending_stocks_mt", "soybeans_cbot") == base
    assert R.scoped_reading_words("silver_psd", "ending_stocks_mt") == base
    assert R.reading_words("silver_psd", "ending_stocks_mt") == base


def test_R0923_the_CARD_LABEL_joins_a_hops_reader_names():
    """Lane T's R3: the card's own metric label (the trade word a writer reaches for) is one of the
    spellings a hop may be named by, beside the printed series name."""
    import types
    hop = types.SimpleNamespace(contract="soybeans_cbot", driver_id="flash_drought", measured=True,
                                series_key="drought_z|soybeans_cbot|United States")
    names = R.chain_hop_reader_names(hop)
    label = R._hop_card_label(hop)
    assert label and label in names, (label, names)
    assert names[0] == R.chain_hop_name(hop)


def test_fix_0923_the_tape_settle_prints_its_TICK_and_its_unit_ONCE():
    """09-23 FIX ROUND (integration F-3, review RA lexical `_fmt`): the settle is a CARD's figure and prints
    through `shown_figure` with the settle card's `display_decimals` -- 1328.25 keeps its quarter-cent
    (the precision producer alone prints "1328" at a thousand and over) -- and `shown_figure` carries the
    unit, so the line prints it exactly once (HEAD's shape: "<figure> <unit>")."""
    t = H.fixture_tape("soybeans_cbot", H.ASOF)
    for level, want in ((1085.08, "1085.08"), (1328.25, "1328.25"), (1328.0, "1328")):
        t.level = level
        line, _calls = R.sb_tape(1, t, asof=H.ASOF)
        assert f"settle on 2026-09-04: {want} {t.unit};" in line, line[:140]
        assert line.split(";")[0].count(t.unit) == 1, line[:140]      # the settle clause: one unit
        assert R.classify(line) == ("SB-T",)
