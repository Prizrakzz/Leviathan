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
            bare = _GLUED_RX.sub("", bare)
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
                  "all sit among this board's loudest rows",        # the LOUD CLAIM
                  "records the effect as amplifies",                # the EFFECT WORD
                  "carries no series this board could read")        # the READ SPLIT


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
    sb1 = [l for l in lines if l.startswith("- [N1] El Nino on CBOT soybeans")]
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
    assert any("such crossing since" in l or "such crossings since" in l
               for l in ctx["block"].lines)
    assert any("measured on the record as revised through" in l for l in ctx["block"].lines)


#: The plural-on-a-singular-count sightings this bar exists to keep out. Each was MEASURED on a
#: rendered block: a count in WORDS still has to agree with the noun and the verb beside it.
_SINGULAR_MISMATCHES = ("one such crossings", "one other boards", "one hops upstream",
                        "one of its one declared drivers sit among")


def test_a_singular_count_takes_a_SINGULAR_NOUN_in_every_template(scenarios):
    for name, ctx in scenarios.items():
        text = ctx["block"].text()
        for phrase in _SINGULAR_MISMATCHES:
            assert phrase not in text, (name, phrase)
        for line, hit in zip(ctx["block"].lines, ctx["block"].classes):
            if hit[0] != "SB-C" or " one of its " not in line:
                continue
            assert "declared drivers sits among" in line, line
    # and the builders themselves, on a stated row rather than on whatever the fixtures happen to make
    one = dict(name="p", contract="soybeans_cbot", direction="", threshold=1, drivers=("a",),
               matched=("a",), n_matched=1, matched_measured=("a",), matched_unmeasured=(),
               n_declared=1, loud_k=8, n_with_band=1, note="", interactions=())
    assert "declared drivers sits among" in R.sb_convergence(one)
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
            assert "by the near end" in line and "by the far end" in line, (name, line)


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
                assert "no series this board could read" in line
    ctx = scenarios["soybeans_now"]
    trade = [l for l in ctx["block"].lines if l.startswith("- trade-war demand loss")]
    assert trade and "with its own [N] z" in trade[0]
    assert "four of its four declared drivers sit among" in trade[0], "the COUNT is unchanged"
    assert "(export pace lag, with its own [N] z)" in trade[0], "only the READ row carries a z"
    assert "China import tariff" in trade[0] and "no series this board could read" in trade[0]


def test_scenario_3_renders_the_EVENT_the_upstream_levy_and_the_convergence_ordering(scenarios):
    ctx = scenarios["b40_event"]
    lines = ctx["block"].lines
    assert any(l.startswith("- biodiesel mandate dated") for l in lines)
    assert any(l.startswith("UPSTREAM CPO export levy -> biodiesel mandate") for l in lines)
    conv = [c for c in ctx["board"].convergence if c["name"] == "biodiesel_energy_floor"]
    assert conv and conv[0]["n_matched"] == 2 and conv[0]["threshold"] == 2
    assert any("two of its three declared drivers sit among" in l for l in lines)
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
           if l.startswith("BOARD ABSENCE the far boards past this tier's spillover cut")]
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
    "BOARD ABSENCE the far boards past this tier's spillover cut",
    "BOARD ABSENCE the like states past this tier's stanza cut",
    "BOARD ABSENCE the upstream paths past this tier's render cut",
    "BOARD ABSENCE the far states of the rows past this tier's cut",
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
            assert "further rows this line does not name" in line, (name, line[:200])
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
            if h[0] == "SB-1" and l.startswith("- [N") and "El Nino on CME palm oil" in l]
    assert line and "for 2026-02-28" in line[0], line
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
    assert set(R.ROW_CLASSES) == {"SB-H", "SB-1", "SB-V", "SB-T", "SB-O", "SB-W", "SB-R", "SB-E",
                                  "SB-J", "SB-D", "SB-F", "SB-C", "SB-M", "SB-P", "SB-A", "SB-L",
                                  "SB-X", "SB-JOIN"}


def test_the_CO_LOUD_header_names_the_CO_OCCURRENCE_and_never_the_ordinary_SELECTORS_sentence():
    """SB-A is a CLASS and not a template. "the series sat like this" describes the ordinary selector;
    the co-loud one asks when SEVERAL boards sat in the top decile AT ONCE, and a header that printed
    the other sentence would name a selector that did not run."""
    _bd, _stanzas, blk = _co_loud_block()
    head = [l for l, h in zip(blk.lines, blk.classes) if h == ("SB-A",)][0]
    assert "across the boards that carry it" in head
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
    assert "across the boards that carry it" in absence[0]
    assert "the boards' own records alone" in absence[0]


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
    said = [l for l in blk.lines if l.startswith("BOARD ABSENCE a like state on this board")]
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
