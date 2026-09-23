"""S8 LANE A -- THE FLAG, THE KWARG AND THE THREE CORRECTING CHAIN LINTS (DESIGN B.6 / B.7).

THE BARS THIS FILE OWNS:

  **THE FLAG**       ``GRAPHRAG_STATE_CHAIN`` is read in exactly ONE place in ``src/``, with
                     ``_state_board_on``'s grammar, default OFF, and nothing under ``state/`` names
                     it. The SEAM gate has three legs and refuses a chain row that is not at a line
                     start.
  **THE APPEND-ONLY LAW** every one of the three lints APPENDS or COUNTS. Measured on the FIVE
                     2026-09-16 SERVED NOTES -- real-seat prose written before any of these rules
                     existed (standing memory ``feedback_negative_corpus_must_be_unseen_prose``):
                     not one sentence, not one ``[N]``/``[E]`` handle and not one digit leaves, the
                     text never shrinks, and a second run appends nothing.
  **THE CEILING**    DESIGN's own acceptance: a lint firing on more than 10% of the sentences in the
                     five notes is too broad and goes back. Measured here on six cells.
  **THE TARGET**     DESIGN B.6 names two sentences of the deep note as L1's target case. Both are
                     MATCHED; the one whose hop carries a served figure is corrected, and the one
                     whose hop carries no series at all is COUNTED and left exactly as written --
                     words are free.
  **THE REGISTER**   every appended clause returns ``desk_register_hits == []``,
                     ``internal_leaks == []``, ``register_leaks == []`` and zero flow / valuation /
                     execution words. DESIGN B.6's own literal for L2 would not: `the graph` is a
                     charged token, and the shipped clause says `the declared sequence` instead.
  **E11**            a spelling that resolves to two different served rows names NOTHING, and a
                     sentence carrying any numeral at all is not a chain sentence.

EVERYTHING RUNS OFFLINE: the board is built from fixture arrays on the REAL DAGs by
``state/__main__.py``; nothing here opens a pg mirror, reaches Athena or spends a cent.
"""
import inspect
import pathlib
import re

import pytest
from leviathan.graphrag import answer as an
from leviathan.graphrag import register as REG
from leviathan.graphrag.state import __main__ as H
from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.rows import status_word

ASOF = H.ASOF
Q = "what is the situation on soybeans now? how is it looking 3 months from now?"
_HANDLE_RX = re.compile(r"\[[NE]\d+\]")
_DIGIT_RX = re.compile(r"\d")

#: THE NEGATIVE CORPUS: the five bodies the 2026-09-16 pre-arm smoke actually served. It is prose
#: nobody wrote for this fence, and the standing memory says that is the only kind that counts -- the
#: S7b advice cut passed 4,000 hand-built sentences and deleted readings on the first 149 fresh ones.
#:
#: BANKED IN THE REPO, 2026-09-22 (round-3 review m-7 / m-8, carried three rounds). Until this sitting
#: the five bodies were read out of ONE session's scratchpad and the fixture called `pytest.skip` when
#: they were absent -- so on every other machine, and on this one the moment its temp is cleared, the
#: append-only law, the second-run idempotence pin, the 10% ceiling and the register pin SKIPPED
#: SILENTLY and this deck still reported green. There is no skip now: a missing corpus is a RED.
#: The precedent is `data/consequence_leg/xl_golden_seam_off.json`, a served block banked in the repo
#: because a pin that cannot find its evidence is not a pin. `tests/fixtures/chain_lints/README.txt`
#: names the origin, the date and the ONE transformation applied (77 em dashes, one en dash and one
#: n-tilde folded to ASCII), and the census dict, the sentence counts and the exact characters the
#: page grows are IDENTICAL to the served UTF-8 bodies on all 30 note x board cells measured.
_NOTES = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "chain_lints"

#: DESIGN B.6's TWO NAMED TARGET SENTENCES, verbatim from the served deep note.
T1 = ("This is the single clearest counterweight to the tight-balance read, and the model places it "
      "one hop upstream of both the stocks-to-use ratio and the WASDE revision that re-prices the "
      "sheet.")
T2 = ("four declared upstream paths (crude, the Renewable Fuel Standard, the biodiesel mandate, and "
      "one further cause) reach the bean price through this reading, so the demand-pull leg has more "
      "than one route in.")


def _build(graph, mode, curated, *, anchors=("soybeans_cbot",), state_chain=True):
    """ONE fixture board through the walk and the render, exactly as ``seam.fill_stage2`` drives it."""
    bd = W.walk(graph=graph, asof=ASOF, mode=mode, anchors=W.resolve_anchors(named=anchors),
                question=Q, state_fn=H.fixture_state_fn(ASOF), key_fn=None, receipts={},
                knobs=B.board_knobs_of(mode), width=2, legb_on=False, stage2=False)
    tape = {slug: H.fixture_tape(slug, ASOF) for slug in bd.anchor_slugs}
    W.stage2(bd, graph, state_fn=H.fixture_state_fn(ASOF), receipts={}, width=2, legb_on=False,
             chains=(curated if state_chain else ()), state_chain=state_chain)
    R.attach_tape(bd, tape, reads_each=0)
    bd.stamp("tape", "fired" if tape else "not_reached")
    ana = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=H.fixture_benchmark_fn(), receipt_fn=None)
    A.analog_leg(bd, ana)
    wr = WA.watch_rows(bd, analogs=ana)
    WA.watch_leg(bd, wr)
    ages = {}
    for r in bd.rows:
        st = r.state
        if st is None or status_word(st.status) != "ok":
            continue
        c = N.age_clause(st.knowledge_date, bd.asof, st.cadence)
        if c:
            ages[r.key] = c
    rec = N.recency_rows(bd, tape_edge=next((t.level_date for t in tape.values() if t.level_date), ""))
    blk = R.render_board(bd, analogs=ana, watch=wr, recency=rec, age_clauses=ages,
                         chain_receipts=None,
                         anchor_label=", ".join(R.board_label(s) for s in bd.anchor_slugs))
    return bd, blk


@pytest.fixture(scope="module")
def graph():
    from leviathan.graphrag import graph as G
    return G.CausalGraph(G.load_contracts(), silver=set(), version="deck")


@pytest.fixture(scope="module")
def curated():
    from leviathan.graphrag.numbers import cascade as CAS
    return list(CAS.load_chain_map()) + list(CAS.load_transmission_map())


@pytest.fixture(scope="module")
def cell(graph, curated):
    """The MAX soybeans board: three rendered chains, nine hops, four of them measured."""
    bd, blk = _build(graph, "max", curated)
    return bd, list(blk.calls)


@pytest.fixture(scope="module")
def notes():
    """THE FIVE SERVED BODIES, OFF THE REPO -- AND NEVER A SKIP. A corpus this deck cannot find is a
    RED and not a quiet pass: four of this file's laws are graded on nothing else."""
    assert _NOTES.is_dir(), (
        "the banked negative corpus is missing: %s (see its README.txt -- these are the five "
        "2026-09-16 served bodies and four of this deck's laws are graded on them)" % (_NOTES,))
    out = {}
    for p in sorted(_NOTES.glob("*.md")):
        txt = p.read_text(encoding="utf-8")
        txt = re.sub(r"(?m)^#\s.*$", "", txt)
        out[p.name] = re.sub(r"(?m)^\*\*Q:\*\*.*$", "", txt).strip()
    assert len(out) == 5, sorted(out)
    assert (_NOTES / "README.txt").is_file()          # the origin travels with the evidence
    return out


def _sents(text):
    toks = REG._SENT_KEEP.split(text)
    return [toks[i] for i in range(0, len(toks), 2) if toks[i].strip()]


def _run(text, calls, bd):
    st = {"tldr": "", "mechanism": text}
    return st, an._chain_lints(st, calls, bd)


def _market_words(slug):
    """A market's own reader words, the way `_chain_market_fence` folds them -- the board label minus
    a leading exchange code. Read off `render.board_label` so the deck never spells a label itself."""
    parts = str(R.board_label(slug) or "").split(" ")
    if len(parts) > 1 and parts[0].isupper():
        parts = parts[1:]
    return an._chain_fold(" ".join(parts)).split()


# ── THE FLAG AND THE SEAM ───────────────────────────────────────────────────────────────────────────
def test_the_flag_is_off_by_default_and_keeps_the_state_board_grammar(monkeypatch):
    monkeypatch.delenv("GRAPHRAG_STATE_CHAIN", raising=False)
    assert an._state_chain_on() is False
    for word in ("on", "ON", " on ", "1", "true", "TRUE"):
        monkeypatch.setenv("GRAPHRAG_STATE_CHAIN", word)
        assert an._state_chain_on() is True, word
    # A MISTYPED VALUE IS OFF, NOT ON. The pre-arm seams lane measured `=yes` logging a full treatment
    # four of five readers would have read as a control; this flag inherits `_state_board_on`'s exact
    # membership test rather than a truthiness test, so the same typo is dark and stays dark.
    for word in ("yes", "y", "enabled", "off", "0", "", "  "):
        monkeypatch.setenv("GRAPHRAG_STATE_CHAIN", word)
        assert an._state_chain_on() is False, word


def test_the_env_variable_is_named_in_exactly_one_file_and_never_under_state(monkeypatch):
    """ONE ENV READ AT THE SEAM (DESIGN B.7). `state/` reads no environment and this law does not bend
    for the chain: the package is graded on its own source by two live doctrine tests, so a second
    reader anywhere under `state/` would be a build failure one deck over and a rollback that does not
    roll back here."""
    root = pathlib.Path(an.__file__).resolve().parents[1]
    read_rx = re.compile(r"environ[^\n]{0,40}GRAPHRAG_STATE_CHAIN|GRAPHRAG_STATE_CHAIN[^\n]{0,40}environ")
    readers = sorted(p.name for p in root.rglob("*.py")
                     if read_rx.search(p.read_text(encoding="utf-8")))
    assert readers == ["answer.py"], readers
    src = pathlib.Path(an.__file__).read_text(encoding="utf-8")
    assert src.count('os.environ.get("GRAPHRAG_STATE_CHAIN"') == 1
    # THE NAME IS DOCUMENTED under `state/` (the flag is what those modules are dark behind) and that
    # is not a read: what the doctrine forbids is the package resolving its own kill-switch, which is
    # why the test greps for the READ and not for the string.
    for p in (root / "state").rglob("*.py"):
        body = p.read_text(encoding="utf-8")
        assert not read_rx.search(body), p.name


def test_the_seam_gate_has_three_legs_and_the_chain_row_must_be_at_a_line_start(monkeypatch):
    """`_state_chain_block_on` is `_state_board_block_on`'s shape with the third leg added, and the
    third leg is ANCHORED: the bare token `CHAIN ` is something a retrieved chunk can carry into the
    volatile prompt (evidence text is rendered raw, newlines and all), and a chain row is a LINE."""
    from leviathan.graphrag.state import render as SR
    blk = SR.SB_MARKER_PREFIX + " a board\n" + SR.CHAIN_HEAD_PREFIX + "first of three, from A to B."
    loose = SR.SB_MARKER_PREFIX + " a board\nthe report said CHAIN OF CUSTODY was broken."
    monkeypatch.delenv("GRAPHRAG_STATE_CHAIN", raising=False)
    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "on")
    assert an._state_chain_block_on(blk) is False                 # leg 1: the kill-switch
    monkeypatch.setenv("GRAPHRAG_STATE_CHAIN", "on")
    assert an._state_chain_block_on(blk) is True
    assert an._state_chain_block_on(loose) is False               # leg 3: at a LINE START, or not at all
    assert an._state_chain_block_on(SR.CHAIN_HEAD_PREFIX + "x") is False   # leg 2: no board, no chain
    assert an._state_chain_block_on("") is False
    assert an._state_chain_block_on(None) is False
    monkeypatch.setenv("GRAPHRAG_STATE_BOARD", "off")
    assert an._state_chain_block_on(blk) is False                 # leg 2: the board's own gate


def test_the_seam_threads_the_flag_and_never_the_environment():
    """The two kwargs lane R and lane N defined, at the one call site each, spelled as they pinned it."""
    from leviathan.graphrag.state import seam as S
    assert "state_chain" in str(inspect.signature(S.fill_stage2))
    assert str(inspect.signature(S.fill_stage2).parameters["state_chain"].default) == "False"
    body = inspect.getsource(an._answer_l2)
    assert "state_chain=_state_chain_on()," in body                # into the board
    assert "state_chain=_state_chain," in body                     # into the persona
    assert "_state_chain = _state_chain_block_on(vp)" in body      # ONE local read, two consumers
    # ...AND THE LOCAL MAY NOT WEAR A MODULE HELPER'S NAME. Round 2's FATAL: spelled `_chain_on`, this
    # local shadowed the module-level cascade-chain kill-switch for the WHOLE of `_answer_l2`, and the
    # call 1,375 lines above it raised UnboundLocalError on every L2 turn with both flags off.
    assert "_chain_on = _state_chain_block_on(vp)" not in body
    assert "if _state_chain:" in body                              # the lints ride the SAME local
    assert "chain=bool(state_chain)" in inspect.getsource(an._system)


# ── THE APPEND-ONLY LAW, ON UNSEEN REAL-SEAT PROSE ──────────────────────────────────────────────────
def test_not_one_sentence_handle_or_digit_leaves_the_five_served_notes(cell, notes):
    bd, calls = cell
    for name, prose in notes.items():
        st, cen = _run(prose, calls, bd)
        after = st["mechanism"]
        assert cen["outcome"] == "ok", (name, cen)
        assert len(_sents(after)) == len(_sents(prose)), name      # NO SENTENCE LEAVES
        for tok in set(_HANDLE_RX.findall(prose)):                 # NO HANDLE LEAVES
            assert after.count(tok) >= prose.count(tok), (name, tok)
        for dig in set(_DIGIT_RX.findall(prose)):                  # NO DIGIT LEAVES
            assert after.count(dig) >= prose.count(dig), (name, dig)
        assert len(after) >= len(prose), name                      # the page never shrinks
        assert st["tldr"] == ""                                    # an empty field is left alone


def test_a_second_run_appends_nothing_twice_on_the_five_served_notes(cell, notes):
    """IDEMPOTENCE, and it is not a nicety: the one-figure-per-sentence cap is read off the SENTENCE
    and not off this run's state precisely because the first cut was not. MEASURED before the fix:
    run 1 appended the first named hop's figure, whose `[N]` then satisfied the already-cited test on
    run 2, so the cap slid to the SECOND named hop and a re-run grew the page."""
    bd, calls = cell
    for name, prose in notes.items():
        st, _ = _run(prose, calls, bd)
        once = st["mechanism"]
        again = an._chain_lints(st, calls, bd)
        assert st["mechanism"] == once, name
        assert again["corrected"] == 0, (name, again)


def test_the_fire_rate_stays_under_the_designs_ten_percent_ceiling(graph, curated, notes):
    """DESIGN's own acceptance line: "any lint that fires on more than 10% of the sentences in the
    five notes is too broad and goes back". SIX CELLS, including two DELIBERATELY MISMATCHED ones (a
    palm board and a corn/wheat board against the soybean notes), because the mismatched pairing is
    where a name-matching fence does its worst -- and it is the cell that measured 14 appends of a
    Malaysian palm figure into soybean sentences before the digit-free rule closed it."""
    cells = (("quick", ("soybeans_cbot",)), ("deep", ("soybeans_cbot",)),
             ("max", ("soybeans_cbot",)), ("max", ("soybean_oil_cbot",)),
             ("max", ("malaysian_crude_palm_oil_cme",)),
             ("max", ("corn_cbot", "soft_red_winter_wheat_cbot")))
    worst = 0.0
    for mode, anchors in cells:
        bd, blk = _build(graph, mode, curated, anchors=anchors)
        calls = list(blk.calls)
        n_s = n_f = 0
        for prose in notes.values():
            st, cen = _run(prose, calls, bd)
            n_s += len(_sents(prose))
            n_f += cen["corrected"]
        rate = 100.0 * n_f / max(1, n_s)
        worst = max(worst, rate)
        assert rate <= 10.0, (mode, anchors, rate, n_f, n_s)
    assert worst <= 7.0, worst          # the MEASURED headroom, so a widening shows up here first


def test_every_appended_clause_is_register_clean(cell, notes):
    """A correcting clause that trips the fence shipping in the same commit is lane R's own W-1
    finding in the other direction. DESIGN B.6's literal for L2 -- "the graph places <hop 2> between
    these two" -- WOULD trip it: `the graph` is a charged `register.DESK_REGISTER_TOKENS` row."""
    bd, calls = cell
    spans = set()
    for prose in notes.values():
        st, _ = _run(prose, calls, bd)
        for before, after in zip(_sents(prose), _sents(st["mechanism"])):
            if before != after:
                spans.add(after.replace(before.rstrip(" .;!?"), "").strip())
    spans |= {an._CHAIN_UNRANKED_CLAUSE,
              an._CHAIN_SKIP_OPEN + "export pace lag" + an._CHAIN_SKIP_CLOSE,
              an._CHAIN_FIGURE_OPEN + "0.117 S/U ratio [N34]" + an._CHAIN_FIGURE_PCT % ("68th", 36)}
    assert spans
    for s in spans:
        assert REG.desk_register_hits(s) == [], s
        assert REG.internal_leaks(s) == [], s
        assert REG.register_leaks(s) == [], s
        assert (REG.count_flow_words(s), REG.count_valuation_words(s),
                REG.count_exec_words(s)) == (0, 0, 0), s
        assert R.register_hits(s) == [], s
    # ...and the design's own L2 literal is the reason the shipped one reads differently.
    assert REG.desk_register_hits(" -- the graph places export pace lag between these two") != []


# ── DESIGN B.6's TWO NAMED TARGET SENTENCES ─────────────────────────────────────────────────────────
def test_L1_corrects_the_deep_notes_first_chain_sentence_at_the_rows_own_address(cell):
    """The measured target case: a topology told in words with no figure a reader could act on. The
    hop is matched through its CARD's declared reader words (`state_conventions.reading_words`
    `silver_psd.su_ratio` -> "the stocks-to-use ratio"), not through the node id, which renders
    `psd ending stock su ratio` -- the writer took the words the block printed beside the row."""
    bd, calls = cell
    st, cen = _run(T1, calls, bd)
    out = st["mechanism"]
    assert out != T1 and out.startswith(T1[:-1])
    assert cen["sentences"] == 1 and cen["corrected"] == 1
    assert an._CHAIN_FIGURE_OPEN in out
    # THE FIGURE IS THE SERVED ROW'S OWN, CHARACTER FOR CHARACTER, AND IT IS CITED AT ITS OWN ADDRESS.
    rows = an._seam_row_index(calls)
    hop = next(h for h in an._chain_hop_rows(bd, calls) if "the stocks to use ratio" in h["names"])
    assert ("%s [N%d]" % (hop["figure"], hop["n"])) in out
    assert rows[hop["n"]]["value"] in out and rows[hop["n"]]["unit"] in out
    assert ("[N%d]" % hop["pct_n"]) in out
    assert out.rstrip().endswith(".")                 # appended INSIDE the sentence's terminator


def test_L1_counts_and_never_corrects_the_deep_notes_second_chain_sentence(graph, curated):
    """DESIGN B.6 names this sentence too, and the honest answer for it is the COUNTER. Its hop is
    `biodiesel_mandate`, a RENDERED hop that carries `silver_status: planned` -- no series, no figure,
    nothing to append. WORDS ARE FREE: the sentence is left exactly as written and
    `chain_hops_unfigured` is what the arm reads (threat E3).

    THE BOARD IS DISCOVERED, NOT ASSUMED (round 2). The hop is what this pin is about; WHICH ranked
    chain carries it is the ranker's business, and the ranker moved under this deck between rounds --
    the max soyoil board rendered it in round 1 and the max palm board renders it now. A pin that
    names one anchor measures the ranker; a pin that names the HOP measures the lint."""
    for anchors in (("soybean_oil_cbot",), ("malaysian_crude_palm_oil_cme",)):
        bd, blk = _build(graph, "max", curated, anchors=anchors)
        calls = list(blk.calls)
        if any(h["printed"] == "biodiesel mandate" and h["n"] is None
               for h in an._chain_hop_rows(bd, calls)):
            break
    else:                                              # pragma: no cover -- the pin must not go quiet
        raise AssertionError("no board on this tree renders the `biodiesel mandate` hop")
    st, cen = _run(T2, calls, bd)
    assert st["mechanism"] == T2                       # NOT ONE CHARACTER MOVES
    assert cen["sentences"] == 1 and cen["chain_hops_unfigured"] == 1
    assert cen["corrected"] == 0


# ── THE THREE LINTS, DRIVEN ─────────────────────────────────────────────────────────────────────────
def test_L2_stamps_the_hop_a_sentence_jumped_and_deletes_nothing(cell):
    """A sentence that walks hop 1 to hop 3 of a chain THIS PAGE RANKED is told what it walked past."""
    bd, calls = cell
    hops = an._chain_hop_rows(bd, calls)
    rank = next(r for r in {h["rank"] for h in hops}
                if len([h for h in hops if h["rank"] == r and h["names"]]) >= 3)
    chain = sorted((h for h in hops if h["rank"] == rank), key=lambda h: h["pos"])
    sent = "%s feeds through to %s here." % (chain[0]["names"][0], chain[2]["names"][0])
    st, cen = _run(sent, calls, bd)
    assert cen["chain_hops_skipped"] == 1, (sent, cen)
    assert an._CHAIN_SKIP_OPEN + chain[1]["printed"] + an._CHAIN_SKIP_CLOSE in st["mechanism"]
    assert st["mechanism"].startswith(sent[:-1]) and st["mechanism"].endswith(".")
    # ADJACENT HOPS ARE NOT A JUMP: nothing sits between them, so nothing is stamped.
    adj = "%s feeds through to %s here." % (chain[0]["names"][0], chain[1]["names"][0])
    st2, cen2 = _run(adj, calls, bd)
    assert cen2["chain_hops_skipped"] == 0 and an._CHAIN_SKIP_OPEN not in st2["mechanism"]


def test_L3_stamps_a_chain_this_page_never_ranked_and_the_sentence_survives(cell):
    """Threat E2, ruling R2's shape: the reader is TOLD, the sentence STAYS. A walk from a hop of one
    rendered chain to a hop of ANOTHER is a sequence no chain on this page carries."""
    bd, calls = cell
    hops = [h for h in an._chain_hop_rows(bd, calls) if h["names"]]
    a = hops[0]
    b = next(h for h in hops if h["rank"] != a["rank"])
    sent = "%s reaches the market through %s." % (a["names"][0], b["names"][0])
    st, cen = _run(sent, calls, bd)
    assert cen["chain_unranked_narrated"] == 1, (sent, cen)
    assert an._CHAIN_UNRANKED_CLAUSE in st["mechanism"]
    assert sent[:-1] in st["mechanism"]                # every word of it survives
    assert cen["chain_hops_skipped"] == 0              # a cross-chain walk is not a skipped hop


def test_two_hops_of_ONE_rendered_chain_are_never_stamped_as_unranked(cell):
    bd, calls = cell
    hops = an._chain_hop_rows(bd, calls)
    rank = next(r for r in {h["rank"] for h in hops}
                if len([h for h in hops if h["rank"] == r and h["names"]]) >= 2)
    pair = sorted((h for h in hops if h["rank"] == rank and h["names"]),
                  key=lambda h: h["pos"])[:2]
    sent = "%s pushes on %s." % (pair[0]["names"][0], pair[1]["names"][0])
    _st, cen = _run(sent, calls, bd)
    assert cen["chain_unranked_narrated"] == 0, (sent, cen)


# ── THE TWO FENCES THAT MAKE IT PRECISE ─────────────────────────────────────────────────────────────
def test_a_sentence_carrying_any_numeral_is_not_a_chain_sentence(cell):
    """DESIGN B.6's "prints no figure for it", read strictly -- and it is the E11 fence at the prose
    end. A sentence with a numeral has already handed the reader a number and an address to check it
    at; the class these lints exist for is the pure topology claim."""
    bd, calls = cell
    hop = next(h for h in an._chain_hop_rows(bd, calls) if h["n"] and h["names"])
    bare = "the sequence runs through %s and out the other side." % (hop["names"][0],)
    st, cen = _run(bare, calls, bd)
    assert cen["corrected"] == 1
    for figured in ("the sequence runs through %s at 4 MMT." % hop["names"][0],
                    "the sequence runs through %s [N%d]." % (hop["names"][0], hop["n"]),
                    "the sequence runs through %s in 2011." % hop["names"][0]):
        st2, cen2 = _run(figured, calls, bd)
        assert st2["mechanism"] == figured, figured
        assert cen2["corrected"] == 0 and cen2["sentences"] == 0, figured


def test_a_spelling_that_names_two_different_served_rows_names_nothing(graph, curated):
    """E11, and the fixture CANNOT fail it, so it is read off the index rather than off a page: two
    hops sharing a spelling AND an address are one reading under two node names (the crush fold) and
    keep it; two hops sharing a spelling and NOT an address both lose it."""
    bd, blk = _build(graph, "max", curated)
    hops = an._chain_hop_rows(bd, list(blk.calls))
    where = {}
    for h in hops:
        for nm in h["names"]:
            where.setdefault(nm, set()).add(h["n"])
    assert all(len(v) == 1 for v in where.values()), where
    # ...and the fold is PRESERVED where it is honest: `soybean crush margin` and `board crush` are
    # two nodes served the same declared reader words, and BOTH keep their own distinct spelling.
    printed = {h["printed"] for h in hops}
    assert printed, printed
    for h in hops:
        assert all(nm in where and h["n"] in where[nm] for nm in h["names"])


def test_a_short_name_is_not_a_match_key_on_its_own(cell):
    """MEASURED on the five served notes: the hop ids under the floor are ordinary desk words
    ("drought", "RFS", "urea"), and a lint that fired on them would be reading the writer's
    vocabulary rather than its narration."""
    bd, calls = cell
    for h in an._chain_hop_rows(bd, calls):
        for nm in h["names"]:
            assert len(nm) >= an._CHAIN_NAME_MIN, (h["printed"], nm)
    assert an._chain_hop_names("drought", None) == ()
    assert an._chain_hop_names("RFS", None) == ()
    assert an._chain_hop_names("export pace lag", None) == ("export pace lag",)


# ── THE BELT, AND THE DARK TURN ─────────────────────────────────────────────────────────────────────
def test_a_board_with_no_rendered_chain_reads_nothing_and_touches_nothing(graph, curated):
    """The flag-off turn, and the one-hop body: `outcome='no_chain'`, no counter, no byte. Stamping
    "not one this page carries" on a turn that HAS no page would tell a reader something false about a
    decision nobody made."""
    bd, blk = _build(graph, "deep", curated, state_chain=False)
    calls = list(blk.calls)
    assert an._chain_hop_rows(bd, calls) == []
    # ONE ANCHOR AND NOT ONE RENDERED CHAIN: the page names ONE market, so no fence exists at all --
    # round 3's replacement for the `_chain_market_fence(("corn_cbot",))` literal, on a REAL board of
    # the shipped type rather than a slug tuple the function no longer takes.
    assert len(bd.anchor_slugs) == 1 and not [c for c in (bd.chains or ()) if c.rendered]
    assert an._chain_market_fence(bd) == {}
    st, cen = _run(T1 + " " + T2, calls, bd)
    assert cen == {"outcome": "no_chain", "sentences": 0, "corrected": 0,
                   "chain_hops_unfigured": 0, "chain_hops_skipped": 0,
                   "chain_unranked_narrated": 0, "chain_hops_ambiguous": 0,
                   "chain_fence_closed": 0}
    assert st["mechanism"] == T1 + " " + T2
    assert an._chain_lints({"tldr": "x", "mechanism": "y"}, calls, None)["outcome"] == "no_chain"


def test_it_never_raises_on_any_shape(cell):
    bd, calls = cell
    assert an._chain_lints(None, calls, bd)["outcome"] == "bad_shape"
    assert an._chain_lints("not a dict", calls, bd)["outcome"] == "bad_shape"
    for bad in ({"tldr": None, "mechanism": 17}, {}, {"mechanism": ""}):
        assert an._chain_lints(bad, calls, bd)["outcome"] == "ok", bad
    assert an._chain_lints({"mechanism": T1}, None, bd)["outcome"] in ("ok", "no_chain")
    assert an._chain_hop_rows(object(), calls) == []
    # ROUND 4 (m-6): AN UNREADABLE BOARD NAMES NO MARKET, AND THAT IS `None` AND NOT `{}`. `{}` is the
    # ONE-MARKET page, which needs no fence by construction; `None` is "I could not read this page's
    # markets", which the caller refuses every figure on. An empty POOL keeps its shape and its
    # meaning moves instead: the caller reads it as "I cannot say what this page carries".
    assert an._chain_market_fence(object()) is None and an._chain_pool_carry(object()) == {}
    assert an._chain_market_fence(None) is None and an._chain_pool_carry(None) == {}
    # NO CALLS IS NOT NO HOPS, and the distinction is the honest one: the rows are on the page either
    # way, they simply have no served figure to offer, so every hop comes back UNFIGURED and L1 can
    # only count. A `[N]` list this pass cannot read is never a licence to invent an address.
    bare = an._chain_hop_rows(bd, None)
    assert bare and all(h["n"] is None and h["pct_n"] is None and h["figure"] == "" for h in bare)
    _st, cen = _run(T1, None, bd)
    assert _st["mechanism"] == T1 and cen["corrected"] == 0


def test_the_append_only_law_is_graded_on_this_files_own_source():
    """`state/lint.py` clause 15 parses answer.py, finds the function that produces each counter and
    fails the build unless it can delete nothing. It is the half that holds with no corpus at all."""
    from leviathan.graphrag.state import lint as LINT
    assert LINT._check_chain_lints_append_only() == []
    assert LINT.check_state_board() == []
    assert not [w for w in LINT.state_board_warnings() if "clause 15" in w]
    src = inspect.getsource(an._chain_lints)
    for counter in LINT.CHAIN_LINT_COUNTERS:
        assert '"%s"' % counter in src, counter
    # GRADED ON THE TREE AND NOT ON THE TEXT -- the same distinction clause 15 itself makes between a
    # clause that grades code and a clause that greps a comment. This docstring QUOTES the served note
    # ("the model places it one hop upstream..."), and a text grep for `del ` finds it inside "model".
    import ast
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(an._chain_lints)))
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Delete)]
    calls = {n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not (calls & set(LINT._CHAIN_LINT_REMOVERS)), sorted(calls)
    assert any(isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
               and any(isinstance(o, ast.In) for o in n.test.ops)
               and len(n.body) == 1 and isinstance(n.body[0], ast.Continue)
               for n in ast.walk(tree))                        # the idempotence guard, by shape


# == ROUND 2 -- THE FOUR MAJORS THE ADVERSARIAL REVIEW MEASURED =======================================
def _run_hp(text, calls, bd):
    """`_run` under the D-HP treatment -- the ONE resolution `_answer_l2` threads into every pass at
    this seat (`_handle_prose_active`, the `*_hp` presets)."""
    st = {"tldr": "", "mechanism": text}
    return st, an._chain_lints(st, calls, bd, handle_prose=True)


@pytest.fixture(scope="module")
def shared_hop_cell(graph, curated):
    """A BOARD WHOSE RENDERED CHAINS SHARE A HOP, which `walk.chain_render_set` permits by
    construction: its diversity rule folds the TOP hop and the RECEIPT hop only, so a shared MIDDLE or
    TERMINAL hop is legal and the shipped `french_rapeseed_matif` board does it at BOTH paid tiers."""
    bd, blk = _build(graph, "max", curated, anchors=("french_rapeseed_matif",))
    return bd, list(blk.calls)


def test_A1_a_hop_two_rendered_chains_share_is_ONE_hop_and_is_never_stamped_as_unranked(
        shared_hop_cell):
    """REVIEW MAJOR A-1. `named` used to carry one entry PER RENDERED LINE, so a hop rendered in two
    chains contributed TWO entries with TWO ranks -- and a sentence naming that ONE hop satisfied both
    legs of L3 and was stamped "this chain is not one this page ranked" about a chain the page ranked
    TWICE. MEASURED before the fix on the five 2026-09-16 served notes against this very board: 7
    stamps at deep and 7 at max, including a FAITHFUL narration of the top chain's own hop 2 -> hop 3.
    Three costs: the page contradicted the block beside it, threat E2's instrument
    (`chain_unranked_narrated`) was poisoned in the direction that reads as over-narration, and L2 was
    SILENCED on those sentences by the `elif`."""
    bd, calls = shared_hop_cell
    hops = an._chain_hop_rows(bd, calls)
    ranks_by_id = {}
    for h in hops:
        ranks_by_id.setdefault(h["id"], set()).add(h["rank"])
    shared = [i for i, r in ranks_by_id.items() if len(r) > 1]
    assert shared, ranks_by_id                        # THE PIN IS NOT VACUOUS: this board shares a hop
    hop = next(h for h in hops if h["id"] == shared[0] and h["names"])
    sent = "in the mechanism reaches the %s here." % (hop["names"][-1],)
    st, cen = _run(sent, calls, bd)
    assert cen["chain_unranked_narrated"] == 0, (sent, cen)
    assert an._CHAIN_UNRANKED_CLAUSE not in st["mechanism"]
    assert cen["sentences"] == 1                      # it WAS read: the hop is named and matched
    # ...and the hop is corrected ONCE, not once per rendered line.
    assert st["mechanism"].count(an._CHAIN_FIGURE_OPEN) <= 1


def test_A1_two_hops_no_rendered_chain_carries_TOGETHER_are_still_stamped(shared_hop_cell):
    """The other half of A-1, so the fix cannot be a silencing: on the SAME board that shares a hop, a
    walk between two hops NO single chain carries is still told it was never ranked.

    ROUND 4 RE-ANCHOR: the discovery gained L3's SECOND leg. This pin looked for a pair no RENDERED
    chain carries, which was L3's whole condition when it was written; round 3 (review MAJOR B-1) made
    the claim require that NO CHAIN OF THE POOL carries them either, and the pair this search happened
    to find first was pool-carried the moment the ranker moved -- so the pin measured the ranker and
    not the lint, for the third sitting running. The condition it searches for is now L3's, read off
    the shipped `_chain_pool_carry`, exactly as its round-3 sibling below does."""
    bd, calls = shared_hop_cell
    hops = [h for h in an._chain_hop_rows(bd, calls) if h["names"]]
    pool = an._chain_pool_carry(bd)
    ranks_by_id = {}
    for h in hops:
        ranks_by_id.setdefault(h["id"], set()).add(h["rank"])

    def _key(h):
        return (h["contract"], h["driver_id"])

    pair = next(((a, b) for a in hops for b in hops
                 if not (ranks_by_id[a["id"]] & ranks_by_id[b["id"]])
                 and not (pool.get(_key(a), set()) & pool.get(_key(b), set()))), None)
    assert pair is not None, ranks_by_id
    sent = "the %s feeds the %s." % (pair[0]["names"][-1], pair[1]["names"][-1])
    st, cen = _run(sent, calls, bd)
    assert cen["chain_unranked_narrated"] == 1, (sent, cen)
    assert an._CHAIN_UNRANKED_CLAUSE in st["mechanism"]


def test_A2_the_hop_row_carries_its_own_contract_and_driver_id_and_the_join_verifies_itself(cell):
    """REVIEW MAJOR A-2 / threat E11: "the state join keys on (contract, driver_id) and the series
    key, NEVER the id alone". `rendered_rows` keeps `role`, `rank`, `cls`, `handles`, `tokens` and
    `line` and DROPS the `label`/`display` the block was built with, so the identity comes off the
    producer's own chain object positionally -- and the join asserts itself against the printed
    name."""
    bd, calls = cell
    hops = an._chain_hop_rows(bd, calls)
    assert hops
    chains = [c for c in (getattr(bd, "chains", None) or ()) if getattr(c, "rendered", False)]
    for h in hops:
        assert isinstance(h["id"], tuple) and len(h["id"]) == 3, h
        assert h["id"] == (h["contract"], h["driver_id"] or h["printed"], h["n"])
        hop = chains[h["rank"] - 1].hops[h["pos"] - 1]
        assert h["driver_id"] == hop.driver_id, h      # the positional join IS the producer's own
        assert h["contract"] == hop.contract, h
        assert R.humanise(hop.driver_id) == h["printed"], h


def test_A2_a_multi_anchor_board_refuses_the_figure_when_the_sentence_names_the_OTHER_market(
        graph, curated, monkeypatch):
    """REVIEW MAJOR A-2, ON THE REAL TURN IT WAS MEASURED ON. corn_cbot + soft_red_winter_wheat_cbot,
    max tier: BOTH rendered chains are corn's and the su-ratio rows served are corn's, so neither the
    address fence nor the spelling fence sees anything -- and L1 appended corn's figure immediately
    after the clause "the same shock into wheat's cushion". A reader takes it as wheat's; it is
    corn's. The estate's own round-3 ruling: a correction that names the wrong row is strictly worse
    than the word it replaced.

    THE FENCE IS A REFUSAL AND NEVER A DELETION -- the sentence ships exactly as the writer wrote it
    and `chain_hops_ambiguous` is what the arm reads."""
    bd, blk = _build(graph, "max", curated, anchors=("corn_cbot", "soft_red_winter_wheat_cbot"))
    calls = list(blk.calls)
    fence = an._chain_market_fence(bd)
    # THE DISCRIMINATING WORD, NEVER THE SHARED ONE -- and never a market's OWN word. The exact tuple
    # is NOT pinned, because round 3 widened the fence to the rendered chains' terminals and WHICH
    # chains render is lane W's ranker: a deck that pins the tuple measures the ranker, not the lint
    # (the round-2b handoff's own lesson, sec 4).
    assert " wheat " in fence["corn_cbot"], fence
    assert " corn " not in fence["corn_cbot"], fence
    assert " corn " in fence["soft_red_winter_wheat_cbot"], fence
    assert " wheat " not in fence["soft_red_winter_wheat_cbot"], fence
    hop = next(h for h in an._chain_hop_rows(bd, calls) if h["n"] and h["names"])
    # WHICH anchor's hop renders first is lane W's ranker (it was corn's in round 2 and wheat's in
    # round 3 on this very fixture), so the two sentences are built from the HOP'S OWN market and the
    # OTHER ANCHOR -- the fact under test is the collision, never which side of it renders.
    assert hop["contract"] in bd.anchor_slugs, hop
    other_anchor = next(s for s in bd.anchor_slugs if s != hop["contract"])
    own_word = _market_words(hop["contract"])[-1]
    other_word = next(w for w in _market_words(other_anchor)
                      if (" " + w + " ") in fence[hop["contract"]])
    other = ("for %s the balance sheet runs through the %s and out the other side."
             % (other_word, hop["names"][0]))
    own = ("for %s the balance sheet runs through the %s and out the other side."
           % (own_word, hop["names"][0]))
    # HEAD's behaviour is this fence ABSENT -- before round 2 the hop row carried no contract at all.
    monkeypatch.setattr(an, "_chain_market_fence", lambda *a, **k: {})
    st_head, cen_head = _run(other, calls, bd)
    assert cen_head["corrected"] == 1 and an._CHAIN_FIGURE_OPEN in st_head["mechanism"]
    monkeypatch.undo()
    st, cen = _run(other, calls, bd)
    assert st["mechanism"] == other                    # NOT ONE CHARACTER MOVES
    assert cen["corrected"] == 0 and cen["chain_hops_ambiguous"] == 1, cen
    assert cen["sentences"] == 1                       # it was READ, and refused with its reason
    st_own, cen_own = _run(own, calls, bd)
    assert cen_own["corrected"] == 1 and cen_own["chain_hops_ambiguous"] == 0, cen_own
    assert "[N%d]" % hop["n"] in st_own["mechanism"]


def test_A2_the_E11_spelling_fence_runs_even_when_the_belt_catches(cell):
    """The other half of the same fence: the dedup block sits AFTER the row loop, so before round 2 a
    mid-loop exception returned the PARTIALLY BUILT rows with the colliding spellings still on them.
    A fence an exception can walk around is not a fence, so it runs in a `finally`.

    The rows are synthetic and the CALLS ARE THE REAL BOARD'S, because the collision this fence exists
    for is between two SERVED ADDRESSES and a hand-made citation would not have any."""
    _bd, calls = cell
    idx = an._seam_row_index(calls)
    a, b = [i for i, r in sorted(idx.items()) if r["value"] and r["unit"]][:2]
    spell = "ending stocks su ratio"
    line = "  chain " + spell + " [N%d]: at the sixty-eighth percentile of its own record."
    assert spell in an._chain_hop_names(spell, None)   # ...so the drop below is a DROP, not an absence

    class _Boom:                                       # `int(rank)` raises -> the belt catches
        def __int__(self):
            raise TypeError("rank")

    board = type("B", (), {"rendered_rows": ({"role": "chain_hop", "rank": 1, "line": line % a},
                                             {"role": "chain_hop", "rank": 2, "line": line % b},
                                             {"role": "chain_hop", "rank": _Boom(), "line": line % a}),
                           "chains": (), "anchor_slugs": ()})()
    rows = an._chain_hop_rows(board, calls)
    assert len(rows) == 2, rows                        # the belt returned what it had built
    assert [r["n"] for r in rows] == [a, b], rows      # two served addresses, one spelling
    assert all(spell not in r["names"] for r in rows), rows      # ...and the fence emptied both


def test_A3_the_treatment_appends_the_handle_alone_and_the_resolver_fills_it_exactly_once(cell):
    """REVIEW MAJOR A-3. `_chain_lints` is seated BEFORE `_resolve_number_handles`, which on the
    `*_hp` presets SPLICES a row's value in front of its own handle unless a numeral sits IMMEDIATELY
    beside it (`_figure_already_stated` / `_HANDLE_ADJ_BEFORE_RX`: whitespace, brackets and quotes
    only). The shipped clause puts the UNIT between the numeral and the handle, so the guard missed
    and the figure was spliced a SECOND time -- D-PQ HANDLE-1's doubled figure, re-minted by the
    correction itself. Under the treatment the clause is the HANDLE ALONE, which is the D-HP contract
    and what the resolver is for."""
    bd, calls = cell
    st_c, cen_c = _run(T1, calls, bd)
    assert cen_c["corrected"] == 1
    # (a) THE DOUBLED SHAPE, pinned as the cause: the control clause through a handle_prose resolver.
    doubled = {"tldr": "", "mechanism": st_c["mechanism"]}
    an._resolve_number_handles(doubled, calls, handle_prose=True)
    assert "0.117 S/U ratio 0.117 S/U ratio" in doubled["mechanism"]
    # (b) ...and the control arm's own resolver leaves it alone, so only the treatment was ever hurt.
    control = {"tldr": "", "mechanism": st_c["mechanism"]}
    an._resolve_number_handles(control, calls, handle_prose=False)
    assert control["mechanism"] == st_c["mechanism"]
    # (c) THE TREATMENT: the handle alone in, the figure ONCE out.
    st_t, cen_t = _run_hp(T1, calls, bd)
    assert cen_t["corrected"] == 1
    assert an._CHAIN_FIGURE_OPEN + "[N" in st_t["mechanism"]
    filled = {"tldr": "", "mechanism": st_t["mechanism"]}
    an._resolve_number_handles(filled, calls, handle_prose=True)
    assert filled["mechanism"].count("0.117 S/U ratio") == 1, filled["mechanism"]
    assert "0.117 S/U ratio 0.117" not in filled["mechanism"]
    # ...and the seat threads the SAME one resolution the passes beside it are threaded with.
    assert "_chain_lints(structured, extra_number_calls, _board, handle_prose=_handles)" \
        in inspect.getsource(an._answer_l2)


# ── ROUND 3: THE POOL IS THE RANKED SET (B-1), AND ONE ANCHOR IS NOT ONE MARKET (B-2) ───────────────
@pytest.fixture(scope="module")
def cornwheat_cell(graph, curated):
    """corn_cbot + soft_red_winter_wheat_cbot at max -- the board the review measured B-1 on: three
    chains render out of a pool of ~3,500 that this same page scored and ordered."""
    bd, blk = _build(graph, "max", curated, anchors=("corn_cbot", "soft_red_winter_wheat_cbot"))
    return bd, list(blk.calls)


def _pool_carried_pairs(bd, hops):
    """``{(hop key, hop key) -> a pool position carrying both}`` over exactly L3's firing condition:
    pairs of DISTINCT rendered hops that NO RENDERED chain carries together."""
    ranks = {}
    for h in hops:
        ranks.setdefault((h["contract"], h["driver_id"]), set()).add(h["rank"])
    pool = an._chain_pool_carry(bd)
    keys = sorted(ranks)
    out = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            both = () if (ranks[a] & ranks[b]) else (pool.get(a, set()) & pool.get(b, set()))
            if both:
                out[(a, b)] = min(both)
    return out


def test_B1_a_sequence_THE_POOL_CARRIES_is_never_stamped_as_one_this_page_does_not(
        cornwheat_cell, monkeypatch):
    """REVIEW MAJOR B-1. `_chain_hop_rows` enumerates `[c for c in board.chains if c.rendered]`, so a
    sequence a POOL chain carries -- scored, ordered and counted by the same page, merely not rendered
    -- was stamped "not one this page ranked". MEASURED on five real boards: 2 of 4 firable pairs
    (rape deep), 2 of 12 (rape max), 5 of 9 (soy deep), 4 of 27 (soy max), 8 of 19 (corn+wheat max),
    and on THIS board the carrying chain scores 60.6 where the rendered #1 scores 60.0.

    THE REVIEWER'S OWN CASE IS `drought + export_pace`, AND IT IS PINNED ON THE PREDICATE RATHER THAN
    THROUGH PROSE, for a reason this pin MEASURES: the `drought` hop carries NO match name at all
    (folded "drought" is 7 characters, under `_CHAIN_NAME_MIN = 8`, and its card declares no reader
    words), so no sentence can name it and L3 could never have reached that pair through the writer.
    The end-to-end half is driven on `La_Nina + export_pace` -- the SAME pool chain, both hops
    nameable."""
    bd, calls = cornwheat_cell
    hops = an._chain_hop_rows(bd, calls)
    pool = an._chain_pool_carry(bd)
    carried = _pool_carried_pairs(bd, hops)
    assert carried, sorted(pool)                       # THE PIN IS NOT VACUOUS: this board has them
    # (a) THE REVIEWER'S LITERAL PAIR, on the predicate, with the reason it cannot be driven in prose.
    drought, pace = ("corn_cbot", "drought"), ("corn_cbot", "export_pace")
    assert drought in pool and pace in pool, sorted(pool)
    both = pool[drought] & pool[pace]
    assert both, (sorted(pool[drought])[:5], sorted(pool[pace])[:5])
    assert not any(c.rendered for i, c in enumerate(bd.chains) if i in both)   # it is a POOL chain
    assert an._chain_hop_names("drought", None) == ()   # ...and no sentence can NAME that hop
    # (b) THE DRIVEN HALF: two NAMEABLE hops that some chain of the pool carries together and NO
    # rendered chain does -- discovered off the board, because WHICH chains render is lane W's ranker
    # and a deck that spells the pair measures the ranker instead of the lint. Today that pair is
    # `La_Nina + export_pace`, on the same 60.6-scoring pool chain as the reviewer's own.
    named = {(h["contract"], h["driver_id"]) for h in hops if h["names"]}
    pair = next((p for p in sorted(carried) if p[0] in named and p[1] in named), None)
    assert pair is not None, (sorted(carried), sorted(named))
    a = next(h for h in hops if (h["contract"], h["driver_id"]) == pair[0] and h["names"])
    b = next(h for h in hops if (h["contract"], h["driver_id"]) == pair[1] and h["names"])
    assert not ({h["rank"] for h in hops if (h["contract"], h["driver_id"]) == pair[0]}
                & {h["rank"] for h in hops if (h["contract"], h["driver_id"]) == pair[1]})
    assert pool[pair[0]] & pool[pair[1]]
    sent = "the %s feeds the %s." % (a["names"][-1], b["names"][0])
    assert not _DIGIT_RX.search(sent), sent
    # ROUND 2'S PREDICATE IS THIS ONE WITH THE POOL BLIND TO THIS PAIR -- and it stamps.
    # ROUND 4 (m-6) CHANGED HOW THAT IS DRIVEN, and the new way is the more honest one: an EMPTY pool
    # now means "I cannot say what this page carries" and WITHHOLDS the stamp, so `lambda: {}` would
    # measure the fail-closed belt instead of round 2's predicate. Round 2 read a pool that was
    # perfectly READABLE and simply did not look at it, which is this dict minus these two keys.
    _blind = {k: v for k, v in pool.items() if k not in (pair[0], pair[1])}
    assert _blind, sorted(pool)                        # still a POOL, merely blind to this pair
    monkeypatch.setattr(an, "_chain_pool_carry", lambda *a_, **k_: _blind)
    st_head, cen_head = _run(sent, calls, bd)
    assert cen_head["chain_unranked_narrated"] == 1, (sent, cen_head)
    assert an._CHAIN_UNRANKED_CLAUSE in st_head["mechanism"]
    monkeypatch.undo()
    st, cen = _run(sent, calls, bd)
    assert cen["chain_unranked_narrated"] == 0, (sent, cen)
    assert an._CHAIN_UNRANKED_CLAUSE not in st["mechanism"]
    assert cen["sentences"] == 1                       # it WAS read, and no claim was made
    assert sent[:-1] in st["mechanism"]                # every word of it survives
    # ...and the clause says what the instrument can see, in the block's own word.
    assert an._CHAIN_UNRANKED_CLAUSE.endswith("this page carries")
    assert "ranked" not in an._CHAIN_UNRANKED_CLAUSE


def test_B1_a_sequence_NO_CHAIN_OF_THE_POOL_carries_is_still_stamped(shared_hop_cell):
    """The other half, so the pool predicate cannot be a silencing: `blocking high` + `IOD positive`
    on the max rapeseed board is genuinely uncomposed -- no chain of the 486 this page ranked carries
    both -- and the reader is still told so, with every word of the sentence on the page."""
    bd, calls = shared_hop_cell
    hops = an._chain_hop_rows(bd, calls)
    pool = an._chain_pool_carry(bd)
    ranks = {}
    for h in hops:
        if h["names"]:
            ranks.setdefault((h["contract"], h["driver_id"]), set()).add(h["rank"])
    keys = sorted(ranks)
    ka, kb = next(((x, y) for i, x in enumerate(keys) for y in keys[i + 1:]
                   if not (ranks[x] & ranks[y]) and not (pool.get(x, set()) & pool.get(y, set()))),
                  (None, None))
    assert ka is not None, (keys, {k: sorted(v)[:3] for k, v in ranks.items()})
    assert ka in pool and kb in pool                   # both ARE hops of chains this page ranked
    assert not (pool[ka] & pool[kb]), (sorted(pool[ka])[:5], sorted(pool[kb])[:5])
    a = next(h for h in hops if (h["contract"], h["driver_id"]) == ka and h["names"])
    b = next(h for h in hops if (h["contract"], h["driver_id"]) == kb and h["names"])
    sent = "the %s feeds the %s." % (a["names"][0], b["names"][-1])
    assert not _DIGIT_RX.search(sent), sent
    st, cen = _run(sent, calls, bd)
    assert cen["chain_unranked_narrated"] == 1, (sent, cen)
    assert an._CHAIN_UNRANKED_CLAUSE in st["mechanism"]
    assert sent[:-1] in st["mechanism"]
    assert cen["chain_hops_skipped"] == 0


def test_B2_a_SINGLE_ANCHOR_board_that_renders_a_cross_chain_is_fenced_too(cell, monkeypatch):
    """REVIEW MAJOR B-2. Round 2's fence was `{}` on a single-anchor board BY CONSTRUCTION -- and a
    single-anchor board RENDERS CROSS CHAINS INTO OTHER MARKETS AND NAMES THEM. On this board (max
    soybeans, ONE anchor) the page reaches BMF corn, ICE canola and CBOT srw wheat, and the sentence
    "the pressure shows up in BMF corn rather than here, and it travels through the export pace lag"
    was given SOYBEANS' `664.8 1000 MT [N7]` with `corrected=1 chain_hops_ambiguous=0`. That is A-2's
    own defect on the board shape that is the MAJORITY.

    THE FAR MARKET IS READ OFF THE BOARD, never spelled into the deck: WHICH chains render is lane
    W's ranker, and a deck that names one measures the ranker instead of the lint."""
    bd, calls = cell
    assert len(bd.anchor_slugs) == 1, bd.anchor_slugs
    rendered = [c for c in (bd.chains or ()) if c.rendered]
    far = sorted({c.terminal for c in rendered if c.terminal} - set(bd.anchor_slugs))
    assert far, [c.terminal for c in rendered]         # NOT VACUOUS: the page names another market
    fence = an._chain_market_fence(bd)
    anchor = bd.anchor_slugs[0]
    assert fence and anchor in fence, fence
    label = R.board_label(far[0])
    word = next((w for w in fence[anchor] if w.strip() in an._chain_fold(label).split()), None)
    assert word, (label, fence[anchor])                # the far market's own word fences this anchor
    for own in an._chain_fold(R.board_label(anchor)).split():
        assert (" " + own + " ") not in fence[anchor], fence   # never a market's OWN word
    hop = next(h for h in an._chain_hop_rows(bd, calls) if h["n"] and h["names"])
    assert hop["contract"] == anchor, hop
    assert all(word not in (" " + nm + " ") for nm in hop["names"]), (word, hop["names"])
    sent = ("the pressure shows up in %s rather than here, and it travels through the %s."
            % (label, hop["names"][0]))
    assert not _DIGIT_RX.search(sent), sent
    # ROUND 2'S BEHAVIOUR IS THIS FENCE ABSENT, and it puts THIS market's figure on THAT market's line.
    monkeypatch.setattr(an, "_chain_market_fence", lambda *a_, **k_: {})
    st_head, cen_head = _run(sent, calls, bd)
    assert cen_head["corrected"] == 1 and an._CHAIN_FIGURE_OPEN in st_head["mechanism"]
    assert hop["figure"] in st_head["mechanism"], st_head["mechanism"]
    monkeypatch.undo()
    st, cen = _run(sent, calls, bd)
    assert st["mechanism"] == sent                     # NOT ONE CHARACTER MOVES
    assert cen["corrected"] == 0 and cen["chain_hops_ambiguous"] == 1, cen
    assert cen["sentences"] == 1                       # it was READ, and refused with its reason
    # ...and the hop's OWN market still gets its own figure on this very board.
    own_sent = "the pressure builds here, and it travels through the %s." % (hop["names"][0],)
    st_own, cen_own = _run(own_sent, calls, bd)
    assert cen_own["corrected"] == 1 and cen_own["chain_hops_ambiguous"] == 0, cen_own
    assert "[N%d]" % hop["n"] in st_own["mechanism"]


def test_the_chain_seam_fields_this_lane_reads_exist_on_the_SHIPPED_TYPES(cell):
    """ROUND 2'S OWN LAW (a): A CROSS-LANE PIN ASSERTS AGAINST THE SHIPPED TYPE. Import `walk.Chain`
    and `walk.ChainHop` and read the REAL field names off the REAL board -- a `types.SimpleNamespace`
    stand-in carrying invented names is how four owner-ordered surfaces rendered nothing while every
    pin in the movement was green. Every field this lane CONSUMES gets one existence pin here, and
    every field it PRODUCES is enumerated in one spelling."""
    import dataclasses
    bd, calls = cell
    chain_fields = {f.name for f in dataclasses.fields(W.Chain)}
    hop_fields = {f.name for f in dataclasses.fields(W.ChainHop)}
    # CONSUMED from lane W's own dataclasses -- `terminal` is round 3's addition (review MAJOR B-2).
    for f in ("contract", "rendered", "hops", "terminal"):
        assert f in chain_fields, (f, sorted(chain_fields))
    for f in ("contract", "driver_id"):
        assert f in hop_fields, (f, sorted(hop_fields))
    # ...and off the BOARD the seat actually hands over, not a stand-in.
    for f in ("anchor_slugs", "chains", "rendered_rows"):
        assert hasattr(bd, f), f
    live = [c for c in bd.chains if c.rendered]
    assert live and all(isinstance(c, W.Chain) for c in bd.chains)
    assert all(isinstance(h, W.ChainHop) for c in live for h in c.hops)
    assert all(isinstance(c.terminal, str) for c in live)
    assert all(isinstance(h.contract, str) and isinstance(h.driver_id, str)
               for c in bd.chains for h in c.hops)
    # PRODUCED: the census this lane hands the seat, the trace and the arm -- seven keys, ONE spelling
    # each, and `chain_unranked_narrated` is threat E2's instrument by that name and no other.
    _st, cen = _run("the mechanism runs somewhere and nothing is named.", calls, bd)
    assert sorted(cen) == ["chain_fence_closed", "chain_hops_ambiguous", "chain_hops_skipped",
                           "chain_hops_unfigured", "chain_unranked_narrated", "corrected",
                           "outcome", "sentences"], cen
    # PRODUCED: the hop row's own eleven keys, which `_chain_hop_rows`' docstring declares.
    rows = an._chain_hop_rows(bd, calls)
    assert rows and all(
        sorted(r) == ["contract", "driver_id", "figure", "id", "n", "names", "pct", "pct_n",
                      "pos", "printed", "rank"] for r in rows), rows[:1]
    # PRODUCED: the pool index's key is `(contract, driver_id)` and its value a set of pool positions.
    pool = an._chain_pool_carry(bd)
    assert pool and all(isinstance(k, tuple) and len(k) == 2 and all(isinstance(x, str) for x in k)
                        for k in pool)
    assert all(isinstance(v, set) and v and all(isinstance(i, int) for i in v)
               for v in pool.values())
    assert max(i for v in pool.values() for i in v) < len(bd.chains)


# == ROUND 4 -- THE TWO FENCES FAIL CLOSED, AND THE LAW HAS ONE SPELLING ==============================
def test_m6_an_UNREADABLE_market_fence_appends_NOTHING_and_the_refusal_is_COUNTED(cell, monkeypatch):
    """REVIEW MINOR m-6, AND IT IS DRIVEN RATHER THAN ASSERTED. Round 3's `_chain_market_fence`
    returned `{}` from its `except`, and the caller reads `{}` as NO FENCE -- so an unreadable display
    vocabulary put back the exact defect the fence exists to stop, SILENTLY, with the counter falling
    to zero as if nothing had been refused.

    MEASURED HERE, on this board: with `render.board_label` raising, round 3 appended THIS market's
    figure to a sentence naming ANOTHER market of the same page. The shipped pass refuses it and says
    so in `chain_fence_closed`."""
    bd, calls = cell
    rendered = [c for c in (bd.chains or ()) if c.rendered]
    far = sorted({c.terminal for c in rendered if c.terminal} - set(bd.anchor_slugs))
    assert far, [c.terminal for c in rendered]         # NOT VACUOUS: the page names another market
    anchor = bd.anchor_slugs[0]
    hop = next(h for h in an._chain_hop_rows(bd, calls) if h["n"] and h["names"]
               and h["contract"] == anchor)
    sent = ("the pressure shows up in %s rather than here, and it travels through the %s."
            % (R.board_label(far[0]), hop["names"][0]))
    assert not _DIGIT_RX.search(sent), sent

    def _boom(_slug):
        raise RuntimeError("the display vocabulary is unreadable")

    # (a) THE FENCE IS READABLE: the sentence is refused its figure for the reason the fence exists.
    st, cen = _run(sent, calls, bd)
    assert st["mechanism"] == sent
    assert cen["chain_hops_ambiguous"] == 1 and cen["chain_fence_closed"] == 0, cen
    # (b) THE FENCE RAISES. Round 3: the figure lands. Round 4: nothing lands, and it is COUNTED.
    monkeypatch.setattr(R, "board_label", _boom)
    assert an._chain_market_fence(bd) is None          # ...and NOT `{}`, which means ONE market
    st_c, cen_c = _run(sent, calls, bd)
    assert st_c["mechanism"] == sent                   # NOT ONE CHARACTER MOVES, either way
    assert cen_c["corrected"] == 0, cen_c              # ROUND 3 SCORED 1 HERE
    assert cen_c["chain_fence_closed"] == 1, cen_c     # the withholding is COUNTED, never silent
    assert cen_c["chain_hops_ambiguous"] == 0, cen_c   # one refusal, ONE counter, one spelling
    assert cen_c["sentences"] == 1                     # it WAS read; the correction was withheld
    assert cen_c["outcome"] == "ok"                    # a closed fence is not a broken lint
    # (c) AND ON THE SAME TURN THE HOP'S OWN MARKET'S SENTENCE GETS NO FIGURE EITHER: a page whose
    # markets cannot be read is a page this correction cannot speak for at all.
    own = "the pressure builds here, and it travels through the %s." % (hop["names"][0],)
    st_o, cen_o = _run(own, calls, bd)
    assert st_o["mechanism"] == own and cen_o["chain_fence_closed"] == 1, cen_o
    monkeypatch.undo()
    st_o2, cen_o2 = _run(own, calls, bd)               # ...and with the fence back, it does
    assert cen_o2["corrected"] == 1 and cen_o2["chain_fence_closed"] == 0, cen_o2


def test_m6_an_EMPTY_pool_withholds_the_L3_stamp_and_COUNTS_it(shared_hop_cell, monkeypatch):
    """THE OTHER HALF OF m-6. Round 3's `_chain_pool_carry` returned `{}` from its `except`, and `{}`
    made every `pool.get(k)` None, `all(held)` False and L3 STAMP -- one `except` restoring the false
    claim B-1 closed. A claim about what this page does NOT carry may not be made on a reading that
    failed. Driven on the board where L3 genuinely fires, so the pin measures the belt and not an
    absence."""
    bd, calls = shared_hop_cell
    hops = an._chain_hop_rows(bd, calls)
    pool = an._chain_pool_carry(bd)
    ranks = {}
    for h in hops:
        if h["names"]:
            ranks.setdefault((h["contract"], h["driver_id"]), set()).add(h["rank"])
    keys = sorted(ranks)
    ka, kb = next(((x, y) for i, x in enumerate(keys) for y in keys[i + 1:]
                   if not (ranks[x] & ranks[y]) and not (pool.get(x, set()) & pool.get(y, set()))),
                  (None, None))
    assert ka is not None, keys                        # NOT VACUOUS: L3 fires on this board
    a = next(h for h in hops if (h["contract"], h["driver_id"]) == ka and h["names"])
    b = next(h for h in hops if (h["contract"], h["driver_id"]) == kb and h["names"])
    sent = "the %s feeds the %s." % (a["names"][0], b["names"][-1])
    st, cen = _run(sent, calls, bd)
    assert cen["chain_unranked_narrated"] == 1 and cen["chain_fence_closed"] == 0, cen
    assert an._CHAIN_UNRANKED_CLAUSE in st["mechanism"]
    # THE POOL COMES BACK EMPTY -- the shape the `except` returns. Round 3 stamped on it.
    monkeypatch.setattr(an, "_chain_pool_carry", lambda *a_, **k_: {})
    st_c, cen_c = _run(sent, calls, bd)
    assert an._CHAIN_UNRANKED_CLAUSE not in st_c["mechanism"], st_c["mechanism"]
    assert cen_c["chain_unranked_narrated"] == 0, cen_c        # ROUND 3 SCORED 1 HERE
    assert cen_c["chain_fence_closed"] == 1, cen_c             # withheld AND counted
    assert cen_c["sentences"] == 1, cen_c                      # it WAS read
    assert cen_c["outcome"] == "ok", cen_c
    # THE WITHHELD STAMP IS THE *ONLY* THING THAT MOVES. L1 is not the pool's business, so whatever
    # figure this sentence earned it still earns -- the belt withholds a CLAIM, never a correction
    # that stands on its own row, and every word the writer wrote is still on the page.
    assert st_c["mechanism"] == st["mechanism"].replace(an._CHAIN_UNRANKED_CLAUSE, ""), (
        st["mechanism"], st_c["mechanism"])
    assert cen_c["corrected"] == cen["corrected"] - 1, (cen, cen_c)
    assert sent[:-1] in st_c["mechanism"]


def test_m6_the_fail_closed_counter_RIDES_THE_TRACE_on_the_seats_own_rule(cell, monkeypatch):
    """A COUNTED WORD THE ARM CANNOT SEE IS A SILENCE WITH EXTRA STEPS. `_answer_l2` stamps
    `sg.trace["chain_lints"]` iff some key other than `outcome` is truthy, so this pin asserts the
    census the seat would stamp -- a fail-closed turn rides -- and reads that rule off the SEAT."""
    bd, calls = cell
    hop = next(h for h in an._chain_hop_rows(bd, calls) if h["n"] and h["names"])
    sent = "the pressure builds here, and it travels through the %s." % (hop["names"][0],)

    def _boom(_slug):
        raise RuntimeError("the display vocabulary is unreadable")

    monkeypatch.setattr(R, "board_label", _boom)
    _st, cen = _run(sent, calls, bd)
    assert cen["chain_fence_closed"] == 1, cen
    assert [v for k, v in cen.items() if k != "outcome" and v], cen     # the seat's own predicate
    monkeypatch.undo()
    # ...and that predicate is READ OFF THE SEAT, never re-spelled here.
    src = inspect.getsource(an._answer_l2)
    assert 'if any(v for k, v in _clints.items() if k != "outcome"):' in src
    assert 'sg.trace["chain_lints"] = _clints' in src
    # the counter is spelled ONCE per place it is produced: the census init and the two withholdings
    lint_src = inspect.getsource(an._chain_lints)
    assert lint_src.count('"chain_fence_closed"') == 3, lint_src.count('"chain_fence_closed"')


def test_the_five_served_notes_go_through_the_SHIPPED_append_only_report(cell, notes):
    """LANE N'S HANDOFF, ITEM 3: ONE RULE, TWO POPULATIONS, NEVER TWO RULES. The append-only law now
    has a PRODUCER (`lint.chain_append_only_report`), which runs the pass twice and grades what the
    reader still has; lane N already routes its conforming reference through it. This deck's own
    assertions above stay -- they measure sentences, handles and digits one by one -- and this pin
    routes the SAME five bodies through the shipped grader so the law cannot mean two things.

    `rep["changed"]` IS THE NON-VACUITY LEG, and it is asserted against the census rather than a
    literal: a body the pass corrected MUST come back changed, and a body it did not must not."""
    from leviathan.graphrag.state import lint as LINT
    bd, calls = cell
    seen_changed = 0
    for name, prose in sorted(notes.items()):
        st = {"tldr": "", "mechanism": prose}
        cen = an._chain_lints(st, calls, bd)
        rep = LINT.chain_append_only_report(an._chain_lints, calls, bd, probe={"mechanism": prose})
        assert rep["raised"] is None, (name, rep["raised"])
        assert rep["errors"] == [], (name, rep["errors"])
        if cen["corrected"]:
            assert rep["changed"] == ["mechanism"], (name, cen, rep["changed"])
            assert len(rep["after"]["mechanism"]) > len(rep["before"]["mechanism"]), name
            seen_changed += 1
        else:
            assert rep["changed"] == [], (name, cen, rep["changed"])
            assert rep["after"]["mechanism"] == rep["before"]["mechanism"], name
    assert seen_changed == 3, seen_changed            # MEASURED on this board: three of the five


# == LANE tracekeys (2026-09-22): THE CENSUS REACHES AN ARTIFACT AND A REPORT ======================
def test_the_census_reaches_the_per_answer_record_and_an_unstamped_row_is_unchanged():
    """THE C2/U3 SILENT-LIFT CLASS, CLOSED FOR THIS PRODUCER -- AND THE BYTE PIN BESIDE IT.

    THE DEFECT, MEASURED AT b9c50701: ``_chain_lints`` returns an EIGHT-key census, ``_answer_l2``
    stamps it on ``sg.trace["chain_lints"]`` under its own ``any(...)`` predicate, and the return
    spreads ``**sg.trace`` wholesale -- so the key reaches ``out['trace']`` with no orchestrator edit at
    all. ``eval.py`` then named it NOWHERE: a grep for ``chain_lints`` over the whole file returned 0,
    and ``_per_answer_record`` returned 209 columns with the IDENTICAL key list whether the trace
    carried the full census or nothing. Five counters an arm was built to read reached no artifact
    column and no report line.

    THE SECOND HALF IS THE ASSERTION THAT WOULD HAVE FAILED UNDER REGISTRATION, and it is the whole
    reason the splat was chosen over ``tracekeys.TRACE_RECORD_KEYS``: a registered key emits ``None`` on
    every control row of every deck forever (and re-anchors 60 negative-index tail pins across eight
    files); a splat emits nothing. MEASURED BOTH WAYS before this test was written -- registering makes
    the flag-off record 210 columns carrying a null ``chain_lints``; the splat leaves it at HEAD's 209
    in HEAD's order. The byte-identical clause decides it, and
    ``test_tracekeys.py::test_a_registered_key_is_present_with_null_and_a_splat_is_absent`` now names
    this key on the SPLAT side (BY SYMBOL, never by line).

    THE LIFT IS VERBATIM, KEY ORDER INCLUDED. A reader must take ``outcome`` before it reads any
    counter as a complete census -- the vocabulary is four words and ``lint_failed:<Exc>`` can arrive
    with partial counters -- so the census must not be re-spelled, re-ordered or flattened on the way
    to the column."""
    from leviathan.graphrag import eval as ev_mod
    from leviathan.graphrag import tracekeys as tk_mod
    from leviathan.graphrag.state import lint as LINT
    census = {"outcome": "ok", "sentences": 2, "corrected": 2, "chain_hops_unfigured": 0,
              "chain_hops_skipped": 0, "chain_unranked_narrated": 0, "chain_hops_ambiguous": 2,
              "chain_fence_closed": 0}
    on = ev_mod._per_answer_record({"q": {"id": "x"}, "out": {"trace": {"chain_lints": census}}},
                                   "single")
    assert on["chain_lints"] == census                             # VERBATIM, the whole eight
    assert list(on["chain_lints"]) == list(census)                 # ...in the producer's own key order
    assert list(on["chain_lints"])[0] == "outcome"                 # read FIRST, by position too
    for c in LINT.CHAIN_LINT_COUNTERS:                             # the roster, never a spelling
        assert c in on["chain_lints"], c
    off = ev_mod._per_answer_record({"q": {"id": "x"}, "out": {"trace": {}}}, "single")
    assert "chain_lints" not in off                                # ABSENT, not None -- the byte pin
    assert "chain_lints" not in ev_mod._per_answer_record({"q": {"id": "x"}, "out": {}}, "single")
    # THE ONE COLUMN IS THE ONLY DIFFERENCE: the flag-off key LIST is the on-row's minus this key, in
    # order. A set comparison would pass while a column silently moved, which is the D-MW P3 defect.
    assert [k for k in on if k != "chain_lints"] == list(off)
    # ...and the key is genuinely NOT registered, so no tail pin in any other deck moved
    assert "chain_lints" not in tk_mod.TRACE_RECORD_KEYS
    assert len(tk_mod.TRACE_RECORD_KEYS) == 47 and tk_mod.TRACE_RECORD_KEYS[-5] == "state_board"


def test_the_state_report_prints_one_chain_line_and_a_deck_with_no_stamp_prints_nothing():
    """LANE tracekeys (2026-09-22). ABSENT IS NEVER ZERO, in the panel too -- and on THIS instrument the
    denominator is load-bearing rather than idiomatic. MEASURED on the five 2026-09-16 banked bodies at
    three tiers: 7 of 15 cells stamp NOTHING while the chain flag is lit and a board is rendered,
    because the prose named no hop the pass could act on. So "no chain_lints column" is not "the flag
    was off", and the line says ``of N turn(s)`` against the rows that stamped one.

    ``outcome`` IS PRINTED FIRST AND THE PARTIAL CENSUSES ARE HELD APART. ``lint_failed:<Exc>`` is the
    one outcome that can reach a row carrying counters (the pass counts as it goes, so a counter raised
    before the exception survives), and a panel that pooled it with the clean rows would report a
    half-run pass as a complete one."""
    from leviathan.graphrag import eval as ev_mod
    from leviathan.graphrag.state import lint as LINT
    rows = [{"out": {"trace": {"chain_lints": {"outcome": "ok", "sentences": 2, "corrected": 2,
                                               "chain_hops_unfigured": 1, "chain_hops_skipped": 0,
                                               "chain_unranked_narrated": 0,
                                               "chain_hops_ambiguous": 2, "chain_fence_closed": 0}}}},
            {"out": {"trace": {"chain_lints": {"outcome": "ok", "sentences": 3, "corrected": 1,
                                               "chain_hops_unfigured": 0, "chain_hops_skipped": 4,
                                               "chain_unranked_narrated": 1,
                                               "chain_hops_ambiguous": 0, "chain_fence_closed": 3}}}}]
    L = ev_mod.state_report(rows)
    hl = [x for x in L if "CHAIN LINTS" in x]
    assert len(hl) == 1
    assert "stamped on 2 of 2 turn(s)" in hl[0] and "'ok': 2" in hl[0]
    pooled = [x for x in L if "chain sentence(s) corrected" in x]
    assert len(pooled) == 1
    assert "3 of 5 chain sentence(s) corrected" in pooled[0]       # 2+1 corrected of 2+3 sentences
    cl = [x for x in L if "`chain_hops_unfigured`" in x]
    assert len(cl) == 1
    for name, tot in (("chain_hops_unfigured", 1), ("chain_hops_skipped", 4),
                      ("chain_unranked_narrated", 1), ("chain_hops_ambiguous", 2),
                      ("chain_fence_closed", 3)):
        assert ("`%s` %d" % (name, tot)) in cl[0], (name, cl[0])
    # THE ROSTER IS READ, NEVER SPELLED: every counter the shipped tuple carries appears on that line,
    # so a sixth counter reaches this report the day it reaches the producer.
    assert all(("`%s`" % c) in cl[0] for c in LINT.CHAIN_LINT_COUNTERS)
    # a chain-only deck takes a header that does not promise a board line (ruling R5)
    assert L[0].startswith("## Chain lints")
    assert not any("board turns" in x for x in L)
    # THE TWO POPULATIONS ARE NAMED APART, never summed into one line
    assert any("chain_referenced" in x and "never summed" in x.lower() for x in L)
    # THE L2-ONLY ABSENCE IS NAMED IN WORDS, never reported as a zero
    assert any("onehop" in x and "one-hop" in x for x in L)
    # NO STAMP ANYWHERE -> the panel does not exist at all, so a banked flag-off report is HEAD's
    assert ev_mod.state_report([{"out": {"trace": {}}}, {"out": {}}]) == []
    # A FAILED LINT PRINTS ITS OUTCOME AND IS EXCLUDED FROM EVERY CLEAN CLAIM. Its counters are partial
    # by construction, so pooling them would report a half-run census as a complete one.
    mixed = ev_mod.state_report(rows + [{"out": {"trace": {"chain_lints": {
        "outcome": "lint_failed:RuntimeError", "sentences": 9, "corrected": 9,
        "chain_hops_unfigured": 0, "chain_hops_skipped": 0, "chain_unranked_narrated": 0,
        "chain_hops_ambiguous": 7, "chain_fence_closed": 0}}}}])
    assert any("lint_failed:RuntimeError" in x for x in mixed)
    assert any("did NOT complete the pass" in x for x in mixed)
    _pool = [x for x in mixed if "chain sentence(s) corrected" in x]
    assert "3 of 5 chain sentence(s) corrected" in _pool[0]        # the failed row's 9 never enters
    _cnt = [x for x in mixed if "`chain_hops_ambiguous`" in x]
    assert "`chain_hops_ambiguous` 2" in _cnt[0]                   # ...and neither does its 7
    # A TRUTHY NON-DICT IS COUNTED AND NAMED, NEVER RAISED (the R5 MINOR rule the board key carries):
    # ``report()`` runs once per deck after a paid arm, so a raise here loses the whole artifact.
    bad = ev_mod.state_report([{"out": {"trace": {"chain_lints": "not a dict"}}}])
    assert any("not a mapping: 1" in x for x in bad)
    assert not any("chain sentence(s) corrected" in x for x in bad)   # nothing scored off a bad shape
