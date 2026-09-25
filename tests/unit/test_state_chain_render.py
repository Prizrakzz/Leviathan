"""S8 LANE R -- THE CHAIN BLOCK: the rows, the receipt, the count line, the caps and the seam.

THE BARS THIS FILE OWNS (DESIGN B.1 / B.3 / B.4 / A.8 / B.6, and the threat model's E1/E3/E4/E6/E9/
E11/E12):

  **THE FLAG**   with ``state_chain`` off NOTHING here exists: no chain row, no count line, no counter
                 key, no moved knob -- and the block is byte-identical to the board-on / chain-off
                 turn arm A measures. TWO flags, one env read at the answer seam, omit-when-empty
                 kwargs.
  **THE CLASS**  every chain row classifies as EXACTLY ONE row class and that class is ``SB-P``, whose
                 role the chain block replaces; the chain's outcome row is ``SB-O``. No new key, so
                 ``state/lint.py``'s clause-10 sample map -- a file this lane does not own -- stays
                 green.
  **THE DIGIT**  the chain rows are LETTERS ONLY: percentiles in words, counts in words, every figure
                 cited at the address that already minted it. The one row that MINTS is the outcome
                 row, and it takes one handle per magnitude.
  **THE REGISTER** every chain line returns ``register_hits == []``, ``internal_leaks == []`` AND
                 ``count_desk_register == 0`` -- a higher bar than the rest of the block keeps, and the
                 reason the page sentences are composed here rather than taken from ``Chain.notes``.
  **THE RECEIPT** DESIGN B.4's order of choice, the two PIT filters, the outside-window correction, the
                 E6 absence wording -- and FREQUENCY IS NOT EVIDENCE: one proposition repeated in six
                 chunks holds ONE seat, the EARLIEST dated instance wins, and the later mentions are
                 counted by DOCUMENT and printed.
  **THE CUT**    the top-ranked chain ALWAYS renders (the orchestrator's 2026-09-17 deviation), the
                 rest are COUNTED and never named, and the ``path_render_cap`` enumeration the count
                 line replaces does not also print.

EVERYTHING RUNS OFFLINE: the board is built from fixture arrays on the REAL DAGs by
``state/__main__.py``; nothing here opens a pg mirror, reaches Athena or spends a cent.
"""
import inspect
import re

import pytest
from leviathan.graphrag import register as REG
from leviathan.graphrag.state import __main__ as H
from leviathan.graphrag.state import analogs as A
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state import lint as LINT
from leviathan.graphrag.state import narration as N
from leviathan.graphrag.state import render as R
from leviathan.graphrag.state import seam as S
from leviathan.graphrag.state import walk as W
from leviathan.graphrag.state import watch as WA
from leviathan.graphrag.state.lagbands import parse_lag
from leviathan.graphrag.state.rows import status_word

_ISO_RX = re.compile(r"\d{4}-\d{2}-\d{2}")
_YEAR_RX = re.compile(r"\b(?:19|20)\d{2}\b")
_YM_RX = re.compile(r"\b\d{4}-\d{2}\b")
_HANDLE_RX = re.compile(r"\[[NE]\d+\]|\[T\d+\]")
_GLUED_RX = re.compile(r"(?<=[A-Za-z])\d+")
#: THE LONG-FORM DAY, exempt by ``verify._claim_number_spans`` rule (d) exactly as an ISO date is by
#: rule (a) -- the 09-23 chain receipt prints a DAY-precision event as "on 10 March 2025" (CONTRACT.md
#: C7), so the letters-only bar admits the one form the verifier already reads as a date.
_LONGDAY_RX = re.compile(r"\b\d{1,2} (?:January|February|March|April|May|June|July|August|September|"
                         r"October|November|December) (?:19|20)\d{2}\b")

ASOF = H.ASOF
Q = "what is the situation on soybeans now? how is it looking 3 months from now?"

#: SIX BYTE-IDENTICAL COPIES OF ONE PROPOSITION, across three documents, beside ONE tail proposition
#: that appears once. THE NEGATIVE CASE THE OWNER'S 2026-09-17 RULING NAMES: a pool where one sentence
#: holds six seats is a pool where the tail proposition loses on volume alone.
_ECHOED: tuple = tuple(
    {"date": "2026-08-2%d" % (i // 2), "event_date": "2026-08-01", "source": "a monthly outlook",
     "tier": 3, "text": "the monthly outlook repeats that the blend mandate is unchanged"}
    for i in range(6)
)
_TAIL_PROP: dict = {"date": "2026-08-05", "event_date": "2026-08-03", "source": "a wire service",
                    "tier": 2,
                    "text": "the authority raised the export levy from the first of the month"}


def _receipt_pool(bd, *, props=None, rows: int = 2) -> dict:
    """A pool in ``seam._receipts_from``'s own shape on the board's OWN loud measured rows."""
    out, hit = {}, 0
    for r in bd.rows:
        st = r.state
        if st is None or status_word(st.status) != "ok" or not r.legs.get("loud"):
            continue
        hit += 1
        if hit > rows:
            break
        out[r.key] = [dict(p) for p in (props if props is not None
                                        else (list(_ECHOED) + [_TAIL_PROP]))]
    return out


def _build(graph, mode, *, state_chain, chains=(), receipts=None, knobs=None):
    """ONE fixture board through the walk and the render, exactly as ``seam.fill_stage2`` drives it."""
    anchors = W.resolve_anchors(named=("soybeans_cbot",))
    kn = knobs if knobs is not None else B.board_knobs_of(mode)
    bd = W.walk(graph=graph, asof=ASOF, mode=mode, anchors=anchors, question=Q,
                state_fn=H.fixture_state_fn(ASOF), key_fn=None, receipts={}, knobs=kn,
                width=2, legb_on=False, stage2=False)
    # ``receipts`` IS THE CELL: ``None`` is this deck's ordinary pool, a CALLABLE is a pool built off
    # THIS board's own rows (the aged-document cell of round 5 needs one), and a dict is passed through.
    rc = (_receipt_pool(bd) if receipts is None
          else (receipts(bd) if callable(receipts) else dict(receipts)))
    tape = {slug: H.fixture_tape(slug, ASOF) for slug in bd.anchor_slugs}
    W.stage2(bd, graph, state_fn=H.fixture_state_fn(ASOF), receipts=rc, width=2, legb_on=False,
             chains=chains, state_chain=state_chain)
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
                         chain_receipts=(rc if state_chain else None),
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
def cells(graph, curated):
    """The two cells every bar here is read against: chain OFF and chain ON, same board, same tier."""
    off_bd, off_blk = _build(graph, "deep", state_chain=False)
    on_bd, on_blk = _build(graph, "deep", state_chain=True, chains=curated)
    return {"off": (off_bd, off_blk), "on": (on_bd, on_blk)}


def _chain_rows(blk):
    return [m for m in blk.rows_meta if str(m.get("role") or "").startswith("chain")
            or str(m.get("label") or "").startswith("chain ")]


def _chain_lines(blk):
    return [str(m.get("line") or "") for m in _chain_rows(blk)]


# ═══ THE FLAG: chain off is today's board, byte for byte ════════════════════════════════════════════
def test_the_chain_flag_off_renders_NO_chain_row_and_the_block_keeps_its_UPSTREAM_lines(cells):
    """B.7's byte-identical set at the RENDER seam. With the flag off `bd.chains` is empty, so the
    section takes the `else` arm and prints exactly the SB-P topology rows the 2026-09-16 smoke had.

    THE TWO ARMS ARE NEVER BOTH ON ONE PAGE, which is the other half of the same claim: the chain rows
    REPLACE the UPSTREAM rows, they do not join them, and printing both would tell the reader the same
    topology twice at twice the bytes."""
    off_bd, off_blk = cells["off"]
    on_bd, on_blk = cells["on"]
    assert list(off_bd.chains) == [] and off_bd.chain_counts == {}
    assert _chain_lines(off_blk) == []
    assert any(x.startswith("UPSTREAM ") for x in off_blk.lines), "the flag-off arm is HEAD's"
    assert on_bd.chains and any(c.rendered for c in on_bd.chains)
    assert not any(x.startswith("UPSTREAM ") for x in on_blk.lines), \
        "the chain block RETIRES sb_path's rows; two spellings of one section is the defect"
    assert callable(R.sb_path), "sb_path stays callable for the flag-off path"


def test_the_path_render_cap_enumeration_does_NOT_also_print_when_the_count_line_carries_it(cells):
    """DESIGN A.8 item 1: the SB-X `path_render_cap` NAME LIST is the largest of the four cuts that buy
    the chain rows their bytes, and the count line says the same closure in counts. Paying for the
    closure twice would be the enumeration this design exists to remove."""
    off_blk, on_blk = cells["off"][1], cells["on"][1]
    _cut = "the upstream paths past this tier's render cut"
    assert any(_cut in x for x in off_blk.lines), "the flag-off arm still names them"
    assert not any(_cut in x for x in on_blk.lines)
    assert any(x.startswith(R.CHAIN_HEAD_PREFIX + "COUNT ") for x in on_blk.lines)


def test_the_coverage_counters_are_ABSENT_on_a_chain_off_board_and_present_on_a_chain_on_one(cells):
    """DESIGN B.6's eleven, under the `_nomination_coverage` splat precedent -- and ABSENT IS NEVER
    ZERO. A census must be able to tell "the chain rendered nothing" from "the chain was never armed"."""
    off_bd, off_blk = cells["off"]
    on_bd, on_blk = cells["on"]
    off = R.board_coverage(off_bd, off_blk.text(), calls=list(off_blk.calls))
    on = R.board_coverage(on_bd, on_blk.text(), calls=list(on_blk.calls))
    assert [k for k in off if k.startswith("chain")] == []
    for key in ("chain_rendered", "chain_referenced", "chain_hops_rendered", "chain_hops_referenced",
                "chain_hops_agreeing", "chain_hops_at_odds", "chain_receipts_rendered",
                "chain_receipts_cited", "chain_events_open", "chain_history_n",
                "chain_below_print_line", "chain_rendered_one_line"):
        assert key in on, key
    assert on["chain_rendered"] == sum(1 for c in on_bd.chains if c.rendered)
    assert isinstance(on["chain_history_n"], list)
    # THE BLOCK SCORED AGAINST ITS OWN TEXT IS THE ZERO-WRITER FLOOR: every row it rendered is present.
    assert on["chain_referenced"] == on["chain_rendered"]
    assert on["chain_hops_referenced"] == on["chain_hops_rendered"]


# ═══ THE CLASS AND THE DIGIT ════════════════════════════════════════════════════════════════════════
def test_every_chain_line_classifies_as_EXACTLY_ONE_class_and_it_is_SB_P_or_SB_O(cells):
    """The disjointness bar on the new rows, measured on real output. The chain rows ride SB-P's own
    class as alternations because `state/lint.py` -- a file this lane does not own -- reds a class with
    no sample; the outcome row rides SB-O, whose clause it widens rather than duplicates."""
    _, blk = cells["on"]
    lines = _chain_lines(blk)
    assert lines, "the deep cell must render at least one chain"
    for line in lines:
        hit = R.classify(line)
        assert len(hit) == 1, f"{hit or 'no class'} for {line[:140]}"
        assert hit[0] in ("SB-P", "SB-O", "SB-R"), f"{hit[0]}: {line[:140]}"
    assert set(R.ROW_CLASSES) == set(R.ROW_CLASSES) | {"SB-P", "SB-O"}
    assert "SB-CHAIN" not in R.ROW_CLASSES, "a new key would red lint clause 10 from a lane that " \
                                            "cannot write its sample"


def test_a_chain_row_carries_NO_charged_digit_and_cites_the_address_that_minted_the_figure(cells):
    """Words are free, digits are not (sec 6.3). A hop's level, z and percentile are on that hop's OWN
    state line under its own handle; a chain row says the standing in WORDS and cites the handle, which
    is `sb_lead`'s own law applied one class over. The OUTCOME row is the one that mints."""
    _, blk = cells["on"]
    for line in _chain_lines(blk):
        if R.classify(line)[0] in R.FIGURE_CLASSES or R.classify(line)[0] in R.DATE_ONLY_CLASSES:
            continue
        bare = _GLUED_RX.sub("", _YEAR_RX.sub("", _YM_RX.sub(
            "", _ISO_RX.sub("", _LONGDAY_RX.sub("", _HANDLE_RX.sub("", line))))))
        assert not any(ch.isdigit() for ch in bare), line[:160]
    # ...and every [N] a chain row REFERENCES points at a call the block actually minted.
    refs = [int(m) for line in _chain_lines(blk) if R.classify(line)[0] == "SB-P"
            for m in re.findall(r"\[N(\d+)\]", line)]
    assert all(1 <= r <= len(blk.calls) for r in refs), refs


def test_every_chain_line_is_register_clean_AND_carries_ZERO_desk_register_charges(cells):
    """**THE HIGHER BAR, AND THE REASON THE PAGE SENTENCES ARE COMPOSED IN `render.py`.**

    The rest of the block may spend `the graph` (SB-E, SB-J, SB-O all do); the chain rows may not, and
    neither may they spend `board`, `rows`, `loud`, `receipt`, `node` or `convention`. That is what
    forced `chain_edge_words`, `sb_chain_sides` and the selection clause to exist beside
    `walk.chain_disagreement_words` and `Chain.notes`, which build the same facts for the TRACE out of
    raw driver ids and the charged token."""
    _, blk = cells["on"]
    for line in _chain_lines(blk):
        assert R.register_hits(line) == [], line[:160]
        assert REG.internal_leaks(line) == [], line[:160]
        assert REG.count_desk_register(line) == 0, (line[:160],
                                                    REG.desk_register_hits(line))
    assert blk.trips == [], [t["hits"] for t in blk.trips]


def test_the_whole_block_is_ASCII_and_the_chain_rows_do_not_weld_into_a_tripping_sentence(cells):
    _, blk = cells["on"]
    blk.text().encode("ascii")
    assert blk.welds == [] or all(w["hits"] for w in blk.welds)


# ═══ THE ROWS THEMSELVES ════════════════════════════════════════════════════════════════════════════
def test_percentile_words_is_an_ENGLISH_ORDINAL_over_the_whole_hundred():
    """`ordinal_words` stops at ten by design; a percentile is the board's most common figure and
    `ordinal()` would print "88th", a charged digit in a letters-only class."""
    assert R.percentile_words(1) == "first"
    assert R.percentile_words(2) == "second"
    assert R.percentile_words(3) == "third"
    assert R.percentile_words(11) == "eleventh"
    assert R.percentile_words(12) == "twelfth"
    assert R.percentile_words(20) == "twentieth"
    assert R.percentile_words(21) == "twenty-first"
    assert R.percentile_words(88) == "eighty-eighth"
    assert R.percentile_words(90) == "ninetieth"
    assert R.percentile_words(99) == "ninety-ninth"
    assert R.percentile_words(100) == "one hundredth"
    assert R.percentile_words(None) == "" and R.percentile_words(101) == ""
    for n in range(0, 101):
        w = R.percentile_words(n)
        assert w and not any(c.isdigit() for c in w), n


def _hop(**kw):
    base = dict(contract="soybeans_cbot", driver_id="crude_oil", sign="+", lag="0-2 quarters",
                lag_band=parse_lag("0-2 quarters"), confidence="high", measured=True,
                series_key="brent_crude_z|_global|", percentile=88.0, z=1.9, run_direction="up",
                run_since="2026-04-30", knowledge_date="2026-09-04", tail=0.76, move=1.0)
    base.update(kw)
    return W.ChainHop(**base)


def _chain(hops, **kw):
    ch = W.Chain(contract="soybeans_cbot", hops=tuple(hops), depth=len(hops) - 1,
                 terminal=kw.pop("terminal", "soybeans_cbot"),
                 agreements=kw.pop("agreements", tuple(["aligned"] * len(hops))),
                 edge_signs=kw.pop("edge_signs", tuple(["+"] * len(hops))), **kw)
    return ch


def test_a_hop_with_NO_measured_row_says_so_in_words_and_the_chain_still_renders():
    """DESIGN B.1's closing clause and threat E3. Existence is a hard filter only in the sense that an
    absent series cannot be PRINTED; it never removes the chain, and the selection clause then shows
    what the chain WAS carried on."""
    hops = [_hop(driver_id="China_import_tariff", measured=False, percentile=None, z=None,
                 series_key="", tail=0.0, run_direction="", run_since="", knowledge_date=""),
            _hop(driver_id="export_pace_lag", percentile=6.0, tail=0.88)]
    ch = _chain(hops)
    ch.terms = {"tail": 22.0, "reach": 10, "event": 0, "history": 7.5, "asymmetry": 5,
                "confidence": 3.0, "lag": 2}
    line = R.sb_chain_hop(ch, 0)
    # 09-23 DESK VOCABULARY (CONTRACT.md C13): "link", not "hop", and the edge is what the MODEL expects;
    # the next hop is named by ITS SERIES (C9), never by its driver id.
    assert "no series is served at this link" in line
    assert ("the model expects it to move %s in the same direction" % R.chain_hop_name(hops[1])) in line
    assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
    assert REG.count_desk_register(line) == 0


def test_an_UNDECLARED_edge_sign_never_reaches_the_page_as_the_charged_fallback():
    """`render.sign_words`' fallback is "in a direction the graph does not declare" -- one charged
    token. The chain's own producer returns the empty string and the caller writes its own clause, so
    an undeclared edge costs the reader nothing and the page no charge."""
    assert R.chain_edge_words("") == ""
    assert R.chain_edge_words("zzz") == ""
    assert R.chain_edge_words("+") == "in the same direction"
    ch = _chain([_hop(), _hop(driver_id="soybean_crush_margin")], edge_signs=("", ""))
    ch.terms = {"tail": 22.0}
    line = R.sb_chain_hop(ch, 0)
    assert "with no direction set between them" in line
    assert "the graph" not in line and REG.count_desk_register(line) == 0


def test_the_agreement_word_is_the_WALKS_and_the_sentence_is_this_pages():
    """One verdict vocabulary, two surfaces. A chain is never ranked down for disagreeing -- the verdict
    is a FIELD -- so the row STATES it and nothing here filters on it."""
    assert set(R.CHAIN_AGREEMENT_CLAUSE) == set(W.CHAIN_AGREEMENT_WORDS)
    for verdict in ("aligned", "at_odds", "undetermined"):
        ch = _chain([_hop(), _hop(driver_id="soybean_crush_margin")],
                    agreements=(verdict, verdict))
        ch.terms = {"tail": 22.0}
        line = R.sb_chain_hop(ch, 0)
        assert R.CHAIN_AGREEMENT_CLAUSE[verdict] in line, verdict
        assert R.classify(line) == ("SB-P",)


def test_the_far_readings_STANDING_prints_only_where_this_page_carries_its_address():
    """A far market's reading lives in `bd.series`, not in `bd.rows`, so on most turns no `[N]` on this
    page points at it. A standing stated with no address is a quantitative claim a reader cannot check
    -- exactly what a letters-only class must not smuggle past the digit rule."""
    ch = _chain([_hop(), _hop(driver_id="soybean_crush_margin")], terminal="soybean_meal_cbot")
    ch.cross = {"other": "soybean_meal_cbot", "sign": "+"}
    ch.terminal_percentile = 9.0
    ch.terms = {"tail": 22.0}
    bare = R.sb_chain_hop(ch, 1)
    assert "percentile of its record" not in bare
    # FIX ROUND 2, fixer pass (REVIEW_RA M2, CONTRACT K10): the standing is the reading the last link's
    # verdict READ (the far board's row of the same driver), handed in WITH its own handle -- never the
    # earned cross's far reading (`Chain.terminal_percentile`, the ONI or China's beginning stocks) printed
    # as the far market's own
    cross_only = R.sb_chain_hop(ch, 1, terminal_handle=42)
    assert "[N42]" in cross_only and "percentile of its record" not in cross_only
    cited = R.sb_chain_hop(ch, 1, terminal_handle=42, terminal_percentile=9.0)
    assert "[N42]" in cited and "sits at the ninth percentile of its record" in cited


# ═══ THE CUT: the top chain always renders ══════════════════════════════════════════════════════════
def test_a_chain_BELOW_the_print_line_renders_as_ONE_LINE_with_its_selection_clause():
    """**THE ONE-LINE FORM, RE-ANCHORED ONTO OWNER RULING 6(a)** (orchestrator release, round 4).
    THE NAME IS HEAD'S AND THE CAUSE HAS MOVED; the pin is kept rather than deleted, because the form
    it guards is the one thing standing between a demoted chain and silence.

    The print line is RETIRED as a selection rule (ruling 6): the top K render IN FULL, always, so a
    chain that "misses the line" is no longer rendered as one line at all -- this pin's old fixture
    (a 40-point chain at k=2) now returns ``full=True, slot='top'`` and the assertion was stale, which
    is the ruling landing rather than a regression.

    THE ONE-LINE FORM'S LIVE CALLER IS THE ``K + 2`` FULL BOUND (``walk.CHAIN_SLOT_FULL_OVER_K``): a
    chain the SELECTION held a seat for -- the question's subject, its pair, its horizon, the other
    side -- seated past that bound renders as ONE line, is never dropped, and is counted on
    ``chain_counts["rendered_one_line"]``. So the pin builds exactly that board: k=1, a top chain that
    answers no slot, and three slot chains behind it.

    AND THE NEGATIVE HALF IS STILL THE POINT: the demoted row carries its own selection clause AND the
    label naming the seat it was held for, because a row that is short BECAUSE it scored low is the
    one a reader most needs the reason for."""
    def _mk(top, second, *, series, score, band, terminal="soybeans_cbot"):
        c = _chain([_hop(driver_id=top, series_key=series, lag_band=parse_lag(band), lag=band),
                    _hop(driver_id=second, series_key=series + "|b", percentile=49.0, tail=0.02)],
                   terminal=terminal)
        c.score = score
        c.terms = {"tail": 20.0, "reach": 10, "history": 5.0}
        c.history = {"n_firings": 0}
        return c
    far = "3-4 quarters"                                  # a horizon of three months sits outside it
    c1 = _mk("crude_oil", "soybean_crush_margin", series="brent_crude_z|_global|", score=90.0,
             band=far)
    c2 = _mk("flash_drought", "export_pace_lag", series="chirps_drought|soybeans_cbot|BR", score=80.0,
             band=far)
    c3 = _mk("RFS", "biodiesel_mandate", series="rfs_policy|_global|", score=70.0, band=far,
             terminal="corn_cbot")
    c4 = _mk("La_Nina", "psd_ending_stock_su_ratio", series="oni_climate|_global|", score=60.0,
             band="0-2 quarters")
    pool = [c1, c2, c3, c4]
    out = W.chain_render_set(pool, k=1, print_line=40.0,
                             subject_ids={"soybeans_cbot": frozenset({"flash_drought"})},
                             named_contracts=("soybeans_cbot", "corn_cbot"), horizon_months=3)
    assert [c.slot for c in out["rendered"]] == ["top", "subject", "pair", "horizon"],         [c.slot for c in out["rendered"]]
    assert all(c.score >= 40.0 for c in pool), "every chain here is ABOVE the old print line"
    assert [c.full for c in out["rendered"]] == [True, True, True, False],         "the top K + %d render in full; the seat past it is the one line" % W.CHAIN_SLOT_FULL_OVER_K
    assert c4.rendered is True and c4.full is False and c4.slot == "horizon"
    assert int(out["counts"].get("rendered_one_line") or 0) == 1, out["counts"]
    assert int(out["counts"].get("below_print_line") or 0) == 0,         "one field, one reading: nothing here is below the line and the count says so"
    one = R.sb_chain_one_line(c4, i=4, n=4, why=R.chain_why_words(c4))
    assert one.startswith(R.CHAIN_HEAD_PREFIX)
    # **ROUND 5, BLOCKER 7: THE ROW STATES THE CAUSE ITS OWN COUNT AGREES WITH.** The row said "under
    # this page's own selection line" on a chain scoring 60.0 against a print line of 40.0, on a board
    # whose `below_print_line` is 0 -- the page contradicting its producer, with THIS pin green over
    # it. The cause is the SEAT: `full` is stamped in seat order, the K + 2 bound was spent, and the
    # chain was carried anyway.
    assert R.CHAIN_ONE_LINE_WORDS["seated"] in one, one
    assert R.CHAIN_ONE_LINE_WORDS["below"] not in one, one
    assert "it is here for" in one, "the one-line form still carries its own selection clause"
    assert R.CHAIN_SLOT_WORDS["horizon"] in one, "and the seat it was held for, by name"
    assert R.classify(one) == ("SB-P",) and R.register_hits(one) == []
    assert REG.count_desk_register(one) == 0
    # AND THE OTHER CAUSE IS NOT DELETED: a chain with NO seat -- the only row a print-line cut can
    # still mint -- keeps the sentence it always had, off the same producer.
    import dataclasses as _dc
    nos = _mk("La_Nina", "psd_ending_stock_su_ratio", series="oni_climate|_global|", score=10.0,
              band="0-2 quarters")
    assert str(getattr(nos, "slot", "") or "") == ""
    cut = R.sb_chain_one_line(nos, i=4, n=4, why=R.chain_why_words(nos))
    assert R.CHAIN_ONE_LINE_WORDS["below"] in cut and R.CHAIN_ONE_LINE_WORDS["seated"] not in cut
    assert R.classify(cut) == ("SB-P",) and R.register_hits(cut) == []
    assert REG.count_desk_register(cut) == 0
    assert _dc.is_dataclass(c4), "every assertion here is against the SHIPPED walk.Chain"
    # ...AND `rendered_one_line` NOW HAS A READER IN THIS MODULE (blocker 10): the counter that carries
    # the fact this row states reaches `board_coverage`, so a census can compare the two.
    assert "rendered_one_line" in inspect.getsource(R._chain_coverage)


def test_the_count_line_COUNTS_and_never_NAMES_and_its_denominators_are_stated(cells):
    """DESIGN B.3. The names are the bytes A.8 cuts; the count with its reasons is what a reader acts
    on. AND IT NAMES BOTH POPULATIONS: the pool is `sequences x the priced markets each carries into`,
    so a line that put the distinct sequence count at the head and the raw pool's sub-counts behind it
    would state one number as the other's subset by grammar alone."""
    bd, blk = cells["on"]
    line = next(x for x in blk.lines if x.startswith(R.CHAIN_HEAD_PREFIX + "COUNT "))
    c = bd.chain_counts
    assert R.words_for_int(int(c["distinct_sequences"])) in line
    # 09-25 FIX ROUND 3 (RT-8): the pool's raw total and its sub-counts are a census the writer copied as one
    # (the chain read's N13); the line counts the distinct chains, those carried above and the rest, not
    # followed -- one population, stated once. The pool arithmetic rides the trace.
    assert "ways in all" not in line and "past one link" not in line
    assert "chains of cause" in line and "the rest are counted here" in line
    assert R.classify(line) == ("SB-P",)
    bare = _GLUED_RX.sub("", _YEAR_RX.sub("", _ISO_RX.sub("", line)))
    assert not any(ch.isdigit() for ch in bare), line
    # NO DRIVER NAME AND NO MARKET NAME LIST -- the enumeration is what this line replaces.
    for c_ in bd.chains:
        for h in c_.hops:
            if c_.rendered:
                continue
            assert R.humanise(h.driver_id) not in line or R.humanise(h.driver_id) in "soybeans"


def test_the_sides_line_says_when_only_one_side_exists_and_names_the_hop_that_runs_against():
    """The owner's 2026-09-17 rule: disagreement is where convexity lives and must be STRUCTURAL. A page
    that prints three chains pointing one way and stays silent about the absence of the other has told
    the reader something it did not measure."""
    a = _chain([_hop(), _hop(driver_id="soybean_crush_margin")])
    a.side, a.against_hops = "for", ()
    assert "points higher for this market" in R.sb_chain_sides([a])
    assert "no other chain on this page points the other way" in R.sb_chain_sides([a])
    b = _chain([_hop(), _hop(driver_id="psd_ending_stock_su_ratio")])
    b.side, b.against_hops = "against", ("export_pace_lag",)
    both = R.sb_chain_sides([a, b])
    assert "point opposite ways" in both and "export pace lag" in both
    for line in (R.sb_chain_sides([a]), both):
        assert R.classify(line) == ("SB-P",) and R.register_hits(line) == []
        assert REG.count_desk_register(line) == 0
    assert R.sb_chain_sides([]) == ""


# ═══ THE RECEIPT: order of choice, PIT, the window, and FREQUENCY IS NOT EVIDENCE ═══════════════════
def test_FREQUENCY_IS_NOT_EVIDENCE_one_proposition_in_six_chunks_holds_ONE_seat():
    """**THE OWNER'S RULING OF 2026-09-17, on the fixture it names.** A proposition repeated across many
    documents or chunks must not crowd the candidate pool or win the receipt by repetition. Six copies
    of one sentence fold to ONE entry; the tail proposition beside them keeps its own seat; and the
    count of later mentions is carried as a number the block can print.

    THE ECHO UNIT IS THE DOCUMENT AND NOT THE CHUNK: six copies across three documents is "reported
    again in two later documents", not five."""
    folded = R.dedupe_props(list(_ECHOED) + [_TAIL_PROP], asof=ASOF)
    assert len(folded) == 2, [p["text"][:40] for p in folded]
    echo = next(p for p in folded if "monthly outlook" in p["text"])
    tail = next(p for p in folded if "export levy" in p["text"])
    assert echo["echoes"] == 2, "three distinct (source, date) documents -> two later ones"
    assert tail["echoes"] == 0
    assert R.echo_words(echo["echoes"]) == "reported again in two later documents"
    assert R.echo_words(1) == "reported again in one later document"
    assert R.echo_words(0) == ""


def test_the_EARLIEST_dated_instance_of_an_event_wins_and_the_later_mentions_are_counted():
    """The first report of a ban IS the action; a later article mentioning it is a mention. A receipt
    row that dates the action to the echo dates it wrong."""
    late = {"date": "2026-08-30", "event_date": "2026-08-15", "source": "a late wire", "tier": 3,
            "text": "the authority raised the export levy from the first of the month"}
    early = {"date": "2026-08-02", "event_date": "2026-08-01", "source": "an early wire", "tier": 1,
             "text": "The AUTHORITY raised the export levy, from the first of the month!!"}
    folded = R.dedupe_props([late, early], asof=ASOF)
    assert len(folded) == 1, "punctuation and case are not proposition identity"
    assert folded[0]["event_date"] == "2026-08-01" and folded[0]["source"] == "an early wire"
    assert folded[0]["echoes"] == 1


def test_PIT_a_proposition_dated_after_the_as_of_never_reaches_a_reader():
    """One of only TWO hard filters in this whole design (the other is existence). Everything else here
    corrects or computes; these two delete, by ruling."""
    future_pub = {"date": "2026-10-01", "event_date": "2026-08-01", "source": "x", "text": "a claim"}
    future_ev = {"date": "2026-08-01", "event_date": "2026-10-01", "source": "y", "text": "b claim"}
    ok = {"date": "2026-08-01", "event_date": "2026-08-01", "source": "z", "text": "c claim"}
    got = R.dedupe_props([future_pub, future_ev, ok], asof=ASOF)
    assert [p["source"] for p in got] == ["z"]
    assert R.dedupe_props([future_pub, future_ev], asof=ASOF) == []
    assert len(R.dedupe_props([future_pub, future_ev, ok], asof="")) == 3, \
        "no as-of is not a filter that passes everything through a different rule"


def test_the_receipt_takes_an_OPEN_action_first_then_a_CLOSED_one_then_a_mechanism_then_says_so():
    """DESIGN B.4's order of choice, and threat E6's wording on the fourth branch: the absence sentence
    names THE DRAW and never the corpus. "none exists" is a claim about a store this turn did not
    read."""
    band = parse_lag("0-2 quarters")
    # 09-24 RE-BANK (OWNER DECISION O-6, CONTRACT K6): an event with NO stated precision is never an
    # action, so these DAY actions state their precision -- the extraction's own field.
    open_ev = {"date": "2026-08-02", "event_date": "2026-08-01", "source": "a wire", "tier": 1,
               "text": "the levy was raised", "event_date_precision": "day"}
    old_ev = {"date": "2021-05-13", "event_date": "2021-05-12", "source": "an old wire", "tier": 3,
              "text": "an older action entirely different in its words", "event_date_precision": "day"}
    mech = {"date": "2026-04-17", "source": "a report", "tier": 2,
            "text": "values are trending higher on biofuel demand"}

    def _one(top_receipts, second_receipts=()):
        h0 = _hop(driver_id="biodiesel_mandate", lag_band=band, receipts_top=tuple(top_receipts),
                  event_receipt=(dict(top_receipts[0]) if top_receipts and
                                 top_receipts[0].get("event_date") else None),
                  event_date=(top_receipts[0].get("event_date") if top_receipts else None),
                  event_open=bool(top_receipts and top_receipts[0].get("event_date") == "2026-08-01"),
                  percentile=95.0, tail=0.9)
        h1 = _hop(driver_id="soybean_crush_margin", lag_band=band,
                  receipts_top=tuple(second_receipts), percentile=50.0, tail=0.0)
        ch = _chain([h0, h1])
        ch.receipt_index = 0
        return ch

    got = R.chain_receipt(_one([open_ev]), None, asof=ASOF)
    assert got["kind"] == "open" and "still open" in got["words"]
    # **CHOICE (2) CARRIES THE WALK'S OWN RECENCY BOUND** (round-4 census 8). A closed action is the
    # chain's receipt only while it sits within ONE BAND-LENGTH of the as-of, which is the rule
    # `walk._chain_receipt` already scores on -- so the 2021 action on a 2026 board is NOT choice (2),
    # and it is not silently promoted to choice (3) either: it is STATED, with its own date.
    got = R.chain_receipt(_one([old_ev]), None, asof=ASOF)
    # THE AGED DOCUMENT NOW RIDES `prop` (09-23, item 4) so the page can cite it at the turn's own
    # evidence-menu address; `kind` stays "none", so it still spends NO seat of the chain's own.
    assert got["kind"] == "none" and got["prop"] is not None, got
    assert got["prop"]["event_date"] == "2021-05-12" and got["event_kind"] == "action_aged"
    assert "older than the lag the model allows for it" in got["words"], got["words"]
    assert "12 May 2021" in got["words"], got["words"]
    near_ev = dict(old_ev, date="2026-08-21", event_date="2026-08-20")
    same = parse_lag("0 quarters")                        # a same-quarter band: closed AND in reach
    inside = _chain([_hop(driver_id="biodiesel_mandate", lag_band=same, receipts_top=(near_ev,),
                          event_receipt=dict(near_ev), event_date="2026-08-20", event_open=False,
                          percentile=95.0, tail=0.9),
                     _hop(driver_id="soybean_crush_margin", lag_band=same, percentile=50.0,
                          tail=0.0)])
    inside.receipt_index = 0
    got = R.chain_receipt(inside, None, asof=ASOF)
    assert got["kind"] == "closed" and "read as history" in got["words"], got["words"]
    got = R.chain_receipt(_one([mech]), None, asof=ASOF)
    assert got["kind"] == "mechanism" and "mechanism" in got["words"]
    got = R.chain_receipt(_one([]), None, asof=ASOF)
    assert got["kind"] == "none" and got["words"] == R.CHAIN_NO_RECEIPT
    assert "none exists" not in R.CHAIN_NO_RECEIPT
    assert "retrieved for this answer" in R.CHAIN_NO_RECEIPT


def test_an_event_OUTSIDE_the_hops_declared_window_renders_with_the_words_never_deleted():
    """Threat E4: the correction, never the deletion. The row renders, and the WORDS place it.

    **AND ROUND 4 SPLIT THE TWO CORRECTIONS THIS ROW CAN CARRY** (census 8). "Outside the declared
    window" is where the action was found at a hop OTHER than the receipt hop and that hop's window
    has closed; "aged out of the window declared for it" is where the action sits more than ONE
    BAND-LENGTH before the as-of, which is the bound `walk._receipt_in_reach` scores on. The first is
    a placement, the second is a refusal -- and the old fixture (a 2021 action on a 2026 board) was
    BOTH, so it is split here: a same-quarter band gives a closed action still in reach, and the 2021
    one keeps its own sentence."""
    band = parse_lag("0 quarters")                        # closed AND in reach: the placement case
    recent = {"date": "2026-08-21", "event_date": "2026-08-20", "source": "a wire", "tier": 3,
              "text": "an action taken before this hop's own window closed", "event_date_precision": "day"}
    old = {"date": "2021-05-13", "event_date": "2021-05-12", "source": "an old wire", "tier": 3,
           "text": "an action taken long before this window", "event_date_precision": "day"}
    h0 = _hop(driver_id="export_pace_lag", lag_band=band, percentile=6.0, tail=0.88)
    h1 = _hop(driver_id="biodiesel_mandate", lag_band=band, receipts_top=(recent,),
              event_receipt=dict(recent), event_date="2026-08-20", event_open=False,
              percentile=50.0, tail=0.0)
    ch = _chain([h0, h1])
    ch.receipt_index = 0
    got = R.chain_receipt(ch, None, asof=ASOF)
    assert got["kind"] == "closed"
    assert R.CHAIN_OUTSIDE_WINDOW in got["words"], got["words"]
    assert "20 August 2026" in got["words"], got["words"]
    # ...AND THE AGED ONE IS REFUSED AS A RECEIPT AND STATED AS A FACT, never deleted and never
    # re-labelled as a mechanism report (which it also qualified as, by its publication date).
    h1b = _hop(driver_id="biodiesel_mandate", lag_band=band, receipts_top=(old,),
               event_receipt=dict(old), event_date="2021-05-12", event_open=False,
               percentile=50.0, tail=0.0)
    ch2 = _chain([h0, h1b])
    ch2.receipt_index = 0
    aged = R.chain_receipt(ch2, None, asof=ASOF)
    assert aged["kind"] == "none" and aged["prop"] is not None, aged
    assert "older than the lag the model allows for it" in aged["words"], aged["words"]
    assert "12 May 2021" in aged["words"] and "mechanism" not in aged["words"]
    row = R.sb_chain_document(aged, aged["hop"])
    assert R.classify(row) == ("SB-P",) and R.register_hits(row) == []


def test_the_chain_CITES_the_events_sections_handle_instead_of_minting_a_second_one(cells):
    """ONE DOCUMENT, ONE ADDRESS (sec 6.3's law, read on the `[E]` surface). Where the EVENTS section
    already put a document on the page under its own handle, the chain cites THAT handle -- a second
    `[E]` for one document is one document under two citations and a reader with no way to know."""
    _, blk = cells["on"]
    docs = [x for x in _chain_lines(blk) if x.startswith(R.CHAIN_SUB_PREFIX + "document:")]
    assert docs, "the deep cell renders at least one chain document line"
    handles = [int(m) for x in blk.lines if x.startswith("- [E")
               for m in re.findall(r"^- \[E(\d+)\]", x)]
    assert len(handles) == len(set(handles)), "one [E] per document, minted once for the block"
    for d in docs:
        for h in re.findall(r"\[E(\d+)\]", d):
            assert int(h) in handles, f"a cited handle points at a row the block never printed: {d}"


#: ONE dated action in the whole estate, more than one band-length before the as-of: the cell blockers
#: 3, 4 and 5 are all measured on. It lands on the board's FIRST loud measured row, which on this
#: fixture is `La_Nina` -- a hop the top chain walks, and NOT that chain's own receipt hop.
_AGED_EVENT, _AGED_DOC = "2019-01-01", "2019-01-05"


def _one_aged_receipt(bd) -> dict:
    for r in bd.rows:
        st = r.state
        if st is None or status_word(st.status) != "ok" or not r.legs.get("loud"):
            continue
        # 09-24 RE-BANK (CONTRACT K13, lane W): a chain rooted on the pole of a declared phase pair that is
        # NOT in force takes no seat, so the document is placed on the first loud row that is not that
        # out-of-force pole -- the fact this pin grades is WHERE the aged document's row prints, not
        # which pole it sits on.
        _pf = R.phase_for_state(st)
        if _pf and _pf.get("in_force") and str(r.driver_id) == str(_pf.get("other_driver") or ""):
            continue
        return {r.key: [{"date": _AGED_DOC, "event_date": _AGED_EVENT, "source": "a wire service",
                         "tier": 2, "text": ("the authority suspended the export licence for the "
                                             "season, and the trade read it as durable"),
                         "event_date_precision": "day"}]}
    return {}


def test_S8R5_the_AGED_document_row_names_the_HOP_THE_DOCUMENT_SITS_ON():
    """**ROUND-5 BLOCKER 4 -- A DATED FACT UNDER A RELATION THE PRODUCER NEVER DECLARED IT AGAINST.**

    :func:`render.chain_receipt`'s aged branch returned ``ch.receipt_hop`` while ``aged`` is a
    ``max()`` over the dates found on ANY hop, so the row's "at <hop>" and its "the window declared for
    it" pointed at a hop that was not the document's and carried a DIFFERENT declared band. That is
    round-3 MAJOR 1's own class, re-introduced by the round-4 fix, and :data:`render.CHAIN_DOCUMENT_AT`
    exists precisely to close it.

    The document here sits on ``La_Nina`` (band 1-2 quarters) and the chain is receipted at
    ``cot_mm_positioning`` (band 0-1 quarters) -- the shape the fixture produces on a real board."""
    old = {"date": _AGED_DOC, "event_date": _AGED_EVENT, "source": "a wire service", "tier": 2,
           "text": "the authority suspended the export licence for the season", "event_date_precision": "day"}
    doc_hop = _hop(driver_id="La_Nina", lag_band=parse_lag("1-2 quarters"), receipts_top=(old,),
                   event_receipt=dict(old), event_date=_AGED_EVENT, event_open=False,
                   percentile=82.0, tail=0.64, series_key="oni_climate|_global|")
    receipt_hop = _hop(driver_id="cot_mm_positioning", lag_band=parse_lag("0-1 quarters"),
                       percentile=94.0, tail=0.88, series_key="cot_mm_positioning|soybeans_cbot|")
    ch = _chain([doc_hop, receipt_hop])
    ch.receipt_index = 1                                  # the CHAIN's receipt hop is the other one
    assert ch.receipt_hop.driver_id == "cot_mm_positioning"
    rp = R.chain_receipt(ch, None, asof=ASOF)
    assert rp["kind"] == "none" and "older than the lag the model allows for it" in rp["words"]
    assert rp["hop"] is doc_hop, (rp["hop"].driver_id, doc_hop.driver_id)
    row = R.sb_chain_document(rp, rp["hop"])
    # THE HOP IS NAMED BY ITS SERIES (09-23, C9) and the date at its own precision (C7).
    assert ("document: at %s, a dated action on 1 January 2019, older than"
            % R.chain_hop_name(doc_hop)) in row, row
    assert R.chain_hop_name(receipt_hop) not in row, row
    assert R.classify(row) == ("SB-P",) and R.register_hits(row) == []
    # AND THE PRODUCER'S OWN PAIR IS READ WHERE IT NAMES THE SAME DOCUMENT (lane W publishes it).
    assert "Chain.aged_receipt_hop" in W.CHAIN_SEAM_FIELDS
    assert "Chain.aged_receipt_date" in W.CHAIN_SEAM_FIELDS


def test_S8R5_ONE_aged_document_prints_ONE_on_the_page_at_the_hop_it_sits_on(graph, curated):
    """**ROUND-5 BLOCKERS 3, 4 AND 5, ON THE PAGE, THROUGH THE REAL PRODUCERS.**

    The estate is given EXACTLY ONE dated action -- 2019-01-01, on the board's first loud measured row
    -- and everything else is the ordinary fixture. Round 4's page answered with three defects at once:

      * **the count line printed a CHAINS x DOCUMENTS product.** ``Chain.receipts_aged_out`` is a
        per-chain document count and ``ChainHop`` is memoised per ``(contract, driver_id)``, so the
        render's sum over the POOL counted the one document once per chain that walked its row:
        "fifty-five / two hundred twenty / TWO HUNDRED SIXTY-FOUR dated actions aged out of their
        windows" on an estate holding ONE;
      * **the document row named the chain's RECEIPT hop** ("at cot mm positioning") for a document
        sitting on ``La_Nina``;
      * **the arithmetic row credited "ACTION SIX"** for the very document the row beside it declined,
        because the walk's MECHANISM branch carried no recency bound while the render's did.

    All three are surfaces, so all three are pinned HERE, on the rendered block."""
    bd, blk = _build(graph, "deep", state_chain=True, chains=curated, receipts=_one_aged_receipt)
    page, rows = blk.text(), {}
    for m in blk.rows_meta:
        rows.setdefault(str(m.get("role") or ""), []).append(str(m.get("line") or ""))
    assert "older than the lag the model allows for it" in page, "the cell must age a document out"
    # (3) ONE DOCUMENT, ONE COUNT, AND THE NOUN AGREES WITH THE NUMBER.
    pool_sum = sum(int(getattr(c, "receipts_aged_out", 0) or 0) for c in bd.chains)
    assert int(bd.chain_counts["receipts_aged_out"]) == 1, bd.chain_counts["receipts_aged_out"]
    assert pool_sum > 1, ("the per-chain field still counts per chain -- that is its own job",
                          pool_sum)
    count_line = next(x for x in blk.lines if x.startswith(R.CHAIN_HEAD_PREFIX + "COUNT "))
    assert "one dated action older than the lag the model allows for it" in count_line, count_line
    assert "dated actions older than" not in count_line, count_line
    assert len(count_line) <= 550, (len(count_line), count_line)
    # (4) THE ROW NAMES THE HOP THE DOCUMENT SITS ON.
    aged_rows = [x for x in rows.get("chain_document", ()) if "older than the lag" in x]
    assert aged_rows, rows.get("chain_document")
    # THE RENDERED CHAIN THAT CARRIES THE DOCUMENT'S HOP. Round 5 read the TOP chain, which walked the
    # document's hop on the fixture it was written against; lane W's 09-23 phase orientation (W-7) moves
    # the cool-phase chain off the top at a warm ONI reading, so the pin now finds the chain by the fact
    # it grades -- the hop the document sits on -- and asserts the same three things about it.
    _ranked = sorted((c for c in bd.chains if c.rendered), key=lambda c: c.rank)
    top = next((c for c in _ranked if any(
        str((h.event_receipt or {}).get("event_date") or "")[:10] == _AGED_EVENT for h in c.hops)),
        _ranked[0])
    on = [h.driver_id for h in top.hops
          if str((h.event_receipt or {}).get("event_date") or "")[:10] == _AGED_EVENT]
    assert on, [h.driver_id for h in top.hops]
    _on_hop = next(h for h in top.hops if h.driver_id == on[0])
    assert all(("at %s," % R.chain_hop_name(_on_hop)) in x for x in aged_rows), (on, aged_rows)
    if str(top.receipt_hop.driver_id) != on[0]:          # the collision this fixture actually mints
        if R.chain_hop_name(top.receipt_hop) != R.chain_hop_name(_on_hop):
            assert not any(("at %s," % R.chain_hop_name(top.receipt_hop)) in x
                           for x in aged_rows), aged_rows
    # (5) AND NO ARITHMETIC ROW CREDITS AN ACTION FOR A DOCUMENT THE SAME PAGE DECLINES.
    assert "%s %s" % (R.CHAIN_TERM_WORDS["event"], R._points_words(6.0)) not in page,         "the walk's mechanism branch is bounded by the same recency rule the render applies"
    assert float((top.terms or {}).get("event") or 0.0) == 0.0, top.terms
    why = [x for x in rows.get("chain_why", ()) if x]
    assert why and not any(re.search(r"%s [a-z]" % R.CHAIN_TERM_WORDS["event"], x)
                           for x in why[:1]), why[:1]
    assert blk.trips == [] and R.register_hits(count_line) == []


def test_the_chain_receipt_cap_is_the_CHAINS_own_and_never_the_per_row_SB_R_cap(graph, curated):
    """DESIGN B.4 in an argument. `receipts_by_row` drives the per-row SB-R enumeration under
    `render_receipts` (0 / 3 / 5 -- ZERO on the free tier, i.e. it would render nothing there);
    `chain_receipts` is read ONLY at a rendered chain's receipt hop under `BoardKnobs.chain_receipts`
    (1 / 2 / 3). Wiring one argument to both would have turned on a section the chain flag never asked
    for and moved a board-on / chain-off turn's bytes."""
    assert "chain_receipts" in str(inspect.signature(R.render_board))
    assert "receipts_by_row" in str(inspect.signature(R.render_board))
    for mode in ("quick", "deep", "max"):
        kn = B.board_knobs_of(mode)
        assert kn.chain_receipts >= 1, mode
    assert B.board_knobs_of("quick").render_receipts == 0, \
        "the per-row cap is ZERO on the free tier -- the chain cannot ride it"
    bd, blk = _build(graph, "quick", state_chain=True, chains=curated)
    minted = [m for m in blk.rows_meta if m.get("role") == "chain_receipt"]
    assert len(minted) <= int(bd.knobs.chain_receipts)


# ═══ THE OUTCOME ROW ════════════════════════════════════════════════════════════════════════════════
def test_the_outcome_row_mints_ONE_HANDLE_PER_MAGNITUDE_and_classifies_as_SB_O():
    """The chain's outcome is the one chain row that MINTS, because the move is a magnitude no other
    row on this page carries. It takes SB-O -- the class that already means "a move over the band
    declared from that state" -- with one handle per magnitude, exactly as `sb_analog_outcome` does."""
    ch = _chain([_hop(), _hop(driver_id="soybean_crush_margin")])
    ch.outcome = {"n": 9, "median_move": 2.1, "low": -4.2, "high": 9.8, "share_declared_way": 6,
                  "unit": "percent", "scope": "the front price's own 2025-06-16 to 2026-09-04 window"}
    ch.declared_sign = "+"
    line, calls = R.sb_chain_outcome(7, ch)
    assert R.classify(line) == ("SB-O",), R.classify(line)
    assert len(calls) == 3 and [c["shown"][0] for c in calls] == [2.1, -4.2, 9.8]
    assert "[N7]" in line and "[N8]" in line and "[N9]" in line
    assert "nine past times this reading sat this far out" in line, line
    assert "six of them the way the model expects" in line, line
    assert "the graph" not in line and REG.count_desk_register(line) == 0
    # ...and a chain with NO price over its firings says so rather than going quiet.
    ch.outcome = {"n": 0}
    assert R.sb_chain_outcome(7, ch) == ("", [])
    absent = R.sb_chain_outcome_absent(ch)
    assert "does not reach back to those past times" in absent
    assert R.classify(absent) == ("SB-P",) and REG.count_desk_register(absent) == 0


def test_the_widened_SB_O_clause_still_classifies_the_shipped_analog_sample_as_exactly_SB_O():
    """The alternation is a WIDENING and not a replacement: `state/lint.py`'s own sample -- a file this
    lane does not own -- must keep classifying as exactly ("SB-O",)."""
    shipped = ("- [N11] the soybean monthly benchmark over the band the graph declares from that "
               "state, one to two quarters: moved 46.33 USD/t by the near end; [N12] moved 68.21 "
               "USD/t by the far end")
    assert R.classify(shipped) == ("SB-O",)
    assert LINT.check_state_board() == []


# ═══ E11: THE STATE JOIN ════════════════════════════════════════════════════════════════════════════
def test_E11_the_chain_row_cites_the_handle_of_ITS_OWN_boards_row_and_never_the_bare_driver_id():
    """`area` is a driver of `corn_cbot` AND of `soft_red_winter_wheat_cbot`, reading the 98th and the
    1st percentile ON THE SAME TURN. `render.series_by_driver` keys on the bare id with `setdefault`
    and returns ONE reading per id for the WHOLE board, so a chain row built off it would print one
    market's tail on another market's chain.

    THE FIXTURE CANNOT FAIL THIS -- it serves one array per ref regardless of scope -- so the rows are
    HAND-MADE, which is what the standing memory asks for."""
    handles = {("corn_cbot", "area"): 11, ("soft_red_winter_wheat_cbot", "area"): 77}
    corn = _hop(contract="corn_cbot", driver_id="area", percentile=98.0, tail=0.96,
                series_key="psd_area|corn_cbot|United States")
    wheat = _hop(contract="soft_red_winter_wheat_cbot", driver_id="area", percentile=1.0, tail=0.98,
                 series_key="psd_area|soft_red_winter_wheat_cbot|United States")
    assert corn.key != wheat.key and corn.fold_key != wheat.fold_key
    ch = _chain([wheat, _hop(contract="soft_red_winter_wheat_cbot", driver_id="ending_stocks")],
                )
    ch.contract = "soft_red_winter_wheat_cbot"
    line = R.sb_chain_hop(ch, 0, handle=handles[wheat.key])
    assert "[N77]" in line and "[N11]" not in line
    assert "at the first percentile of its own record" in line
    assert "ninety-eighth" not in line


# ═══ THE SEAM ═══════════════════════════════════════════════════════════════════════════════════════
def test_the_seam_gains_state_chain_as_a_kwarg_that_DEFAULTS_OFF_and_reads_no_environment():
    """B.7: `state/` reads NO environment and that law does not bend here. `answer._state_chain_on()`
    is the ONE read, at the answer seam, beside `_state_board_on()` and `_watch_nonobvious_on()`, and
    it arrives as a kwarg -- so `config_check.check_state_seam` stays at zero errors."""
    from leviathan.graphrag import config_check as cc
    sig = inspect.signature(S.fill_stage2)
    assert "state_chain" in sig.parameters
    p = sig.parameters["state_chain"]
    assert p.default is False and p.kind is inspect.Parameter.KEYWORD_ONLY
    src = inspect.getsource(S.fill_stage2)
    assert "state_chain=bool(state_chain)" in src
    assert "chain_receipts=(_rcpt if state_chain else None)" in src
    assert "receipts_by_row=None" in src, "the declared residual is NOT what the chain wires"
    assert cc.check_state_seam() == []
    # `config_check.check_state_seam` IS THE PRODUCER OF THIS CLAIM and it grades the SOURCE; the
    # module may NAME a flag in its prose -- that is where a reader learns which switch owns which
    # bytes -- and may never READ one. Asserting it here a second time by substring would grade the
    # docstrings, which is how a source pin turns into a prose ban.
    assert "os" not in {a.name for n in __import__("ast").walk(__import__("ast").parse(
        inspect.getsource(S))) if isinstance(n, __import__("ast").Import) for a in n.names}


def test_the_curated_maps_are_loaded_ONLY_when_the_chain_leg_is_armed():
    """`chain_paths` runs on EVERY board and stamps `notes[kind=chains]`, so loading the twelve curated
    rows unconditionally would move that note -- and therefore the `state_board` payload -- on a
    board-on / chain-off turn, which is the one property arm A needs to attribute a character."""
    assert S._curated_chains(False) == ()
    on = S._curated_chains(True)
    assert len(on) >= 10, len(on)
    assert all(isinstance(r, dict) for r in on)
    assert any("hops" in r for r in on) and any("links" in r for r in on), \
        "BOTH shapes: chain_map is driver NODES, transmission_map is MARKET to MARKET"


def test_the_seam_threads_ONE_receipt_read_to_the_walk_and_to_the_chain():
    """`ground()` has already paid for `n.evidence`, so the board's text tier costs zero reads. One
    call, two readers, so the walk's per-row receipts and the chain's wider pool can never see
    different documents."""
    src = inspect.getsource(S.fill_stage2)
    assert src.count("_rcpt = _receipts_from(sg)") == 1, "one call, or the two readers can disagree"
    assert "receipts=_receipts_from(sg)" not in src, "the second call was the drift this closes"
    assert "receipts=_rcpt" in src and "chain_receipts=(_rcpt" in src


# ═══ THE VOCABULARY ═════════════════════════════════════════════════════════════════════════════════
def test_every_chain_reason_word_a_reader_can_meet_has_a_DIGIT_FREE_sentence():
    """`lint._check_absence_vocabulary` (clause 9) in both directions. Lane W minted the three words in
    `board.CHAIN_REASONS`; until the sentences landed here `lint.check_state_board()` returned three
    errors and four decks were red on that one cause."""
    for word in B.CHAIN_REASONS:
        why = R.ABSENCE_WHY.get(word)
        assert why, word
        assert why == R.absence_why(word)
        assert not any(c.isdigit() for c in why), (word, why)
        why.encode("ascii")
    assert set(B.CHAIN_REASONS) >= {"below_print_line", "no_measured_hop", "cross_unpriced"}
    assert LINT.check_state_board() == []


def test_no_chain_line_teaches_the_words_the_desk_register_bans():
    """Threat E12 and the fix lane's own sweep of the block. The count line's first draft in DESIGN B.3
    reads "the graph carries N further chains into this board" -- two charged tokens in one clause."""
    for const in (R.CHAIN_NO_RECEIPT, R.CHAIN_OUTSIDE_WINDOW, R.CHAIN_WHY_REACH,
                  R.CHAIN_WHY_UNNAMED, R.CHAIN_WHY_EVENT_OPEN, R.CHAIN_WHY_EVENT_CLOSED,
                  R.CHAIN_WHY_EVENT_DOC, R.CHAIN_WHY_ASYM, R.CHAIN_WHY_CURATED,
                  *R.CHAIN_AGREEMENT_CLAUSE.values(), *[w for _f, w in R._TAIL_WORDS]):
        assert REG.count_desk_register(const) == 0, const
        assert R.register_hits(const) == [], const
        const.encode("ascii")


# === 09-23 FIX ROUND, LANE R: THE CHAIN'S PAGE WORDS (CONTRACT.md C2, C7, C9, C13) =====================
def test_R0923_the_history_line_prints_the_TRACES_OWN_FIGURES_in_desk_words():
    """The page twin of `walk.chain_history_words`: the same five facts, the words a desk uses."""
    h = {"n_firings": 8, "aligned": 5, "at_odds": 3, "undetermined": 0, "unmeasured": 8}
    line = R.chain_record_words(h)
    assert line == ("of the past times this reading sat this far out, eight had a next reading to "
                    "measure: the next link moved the way the model expects in five and went the other "
                    "way in three; eight more times no next reading was published inside the lag the "
                    "model allows"), line
    assert REG.count_desk_register(line) == 0 and R.register_hits(line) == []
    # EVERY FIGURE IS THE TRACE'S: the words back-translate to the dict, one number per fact.
    words = {R.words_for_int(k): k for k in range(0, 200)}
    assert [words[w] for w in re.findall(r"\b(eight|five|three)\b", line)] == [8, 5, 3, 8]
    thin = R.chain_record_words({"n_firings": 0, "unmeasured": 14})
    assert "fourteen times before" in thin and "the record is thin" in thin
    und = R.chain_record_words({"n_firings": 6, "aligned": 2, "at_odds": 1, "undetermined": 3})
    assert "went the other way in one and settled no direction in three" in und, und
    for x in (thin, und, R.chain_record_words({"n_firings": 2, "aligned": 1})):
        assert REG.count_desk_register(x) == 0 and not re.search(r"\d", x), x


def test_R0923_the_chain_PAGE_SENTENCE_is_one_sentence_within_its_limits():
    """C9 / threat A-3: <= 45 words, <= 3 named nodes, no digit but the [N] handles, clean on every
    detector and on the EXTENDED desk table; "" when no hop carries a handle."""
    a = _hop(driver_id="crude_oil", series_key="brent_crude_z|_global|")
    b = _hop(driver_id="soybean_crush_margin", series_key="cbot_board_crush_margin|_global|")
    c = _hop(driver_id="psd_ending_stock_su_ratio",
             series_key="psd_ending_stock_su_ratio|soybeans_cbot|United States")
    ch = _chain([a, b, c], terminal="soybeans_no_1_dce",
                agreements=("aligned", "aligned", "undetermined"))
    handles = {a.key: {"level": 54}, c.key: {"level": 36}}
    s = R.chain_page_sentence(ch, handles)
    assert s.startswith("One chain the data carries runs from ") and s.endswith(".")
    assert len(s.split()) <= R.CHAIN_PAGE_SENTENCE_MAX_WORDS, (len(s.split()), s)
    # 09-23 FIX ROUND (review RA M1): the hop is named by its OWN ROW IDENTITY, basis included -- "the
    # stocks-to-use ratio, ending stocks as a share of domestic use, for United States" -- so this chain's
    # two-hop form runs past the 45-word limit and the producer's own rule drops that node rather than
    # break the limit (or print the ratio without its basis, the tariff F1 wording the backstop printed)
    assert "[N54]" in s and "[N36]" not in s and "stocks-to-use ratio for United States" not in s
    assert not re.search(r"\d", re.sub(r"\[N\d+\]", "", s)), s
    assert "two of three links" in s
    assert REG.count_desk_register(s) == 0 and R.register_hits(s) == [] and REG.internal_leaks(s) == []
    assert R.chain_page_sentence(ch, {}) == ""
    # ...and where both named hops fit, both are named, each at its own address
    ch2 = _chain([a, b], terminal="soybeans_no_1_dce", agreements=("aligned", "aligned"))
    s2 = R.chain_page_sentence(ch2, {a.key: {"level": 54}, b.key: {"level": 36}})
    assert "[N54]" in s2 and "[N36]" in s2 and len(s2.split()) <= R.CHAIN_PAGE_SENTENCE_MAX_WORDS, s2


def test_R0923_the_chain_row_cites_EVERY_figure_at_its_OWN_address_on_the_rendered_fixture(cells):
    """C2 / D1: a hop line whose words carry a percentile or a peak carries that figure's own handle,
    minted on the hop's own SB-1 row -- the window peak the 09-23 writer re-digitised and the verifier
    then cut. Every [N] a chain row cites resolves to a call of the right STAT."""
    _, blk = cells["on"]
    stat_of = {i + 1: str((c.get("rows") or [{}])[0].get("stat") or "") for i, c in enumerate(blk.calls)}
    seen_peak = 0
    for line in _chain_lines(blk):
        if not line.startswith(R.CHAIN_SUB_PREFIX) or ": " not in line:
            continue
        m = re.search(r"(peaked at|bottomed at) the [a-z -]+ percentile \[N(\d+)\] in ", line)
        if m:
            seen_peak += 1
            assert stat_of.get(int(m.group(2))) == "window_peak_percentile", (line, m.group(2))
        for pm in re.finditer(r"now the [a-z -]+ \[N(\d+)\]|percentile of its own record \[N(\d+)\]", line):
            h = int(pm.group(1) or pm.group(2))
            assert stat_of.get(h) == "percentile", (line, h)
    assert seen_peak >= 1, "the fixture renders at least one in-transit hop"


def test_R0923_a_measured_hop_is_named_by_its_SERIES_never_by_the_driver_that_routes_to_it():
    """C9: `chain_hop_name` reads the hop's own series key -> the card's declared reader words; an
    UNMEASURED hop has no series and keeps its driver's display words."""
    flash = _hop(driver_id="flash_drought", series_key="drought_z|soybeans_cbot|United States")
    name = R.chain_hop_name(flash)
    assert name.startswith(R.reading_words("gold_weather_z", "drought_z")), name
    assert "flash" not in name.lower(), name
    assert "for United States" in name
    none = _hop(driver_id="China_import_tariff", measured=False, series_key="")
    assert R.chain_hop_name(none) == R.humanise("China_import_tariff")
    names = R.chain_hop_reader_names(flash)
    assert names[0] == name and R.humanise("flash_drought") in names


def test_R0923_the_receipt_words_carry_the_DATE_AT_ITS_PRECISION_and_the_EVENT_KIND():
    """C7: a year-precision date is "during 2026", never "on 2026-01-01" (cotton FA-5); a forecast is a
    forecast "-- not an action"; a policy regime is stated as the model's rule and never as a fact."""
    iv = R._event_interval("2026-01-01", "year")
    assert R.event_when_words(iv, "year") == "during 2026"
    assert R.event_when_words(R._event_interval("2026-01-01", "quarter"), "quarter") == \
        "in the first quarter of 2026"
    assert R.event_when_words(R._event_interval("2026-01-10", "month"), "month") == "in January 2026"
    assert R.event_when_words(R._event_interval("2025-03-10", "day"), "day") == "on 10 March 2025"
    g = R._event_words("guidance", event_date="2026-01-01", precision="year", published="2026-04-03")
    assert g == "a dated forecast, published 3 April 2026, about 2026 -- not an action", g
    r = R._event_words("regime_in_force", event_date="2025-03-10", precision="day")
    assert "the newest dated policy action on this link that this turn retrieved is 10 March 2025" in r
    assert "the model treats a policy as in force until a later dated action on the same link" in r
    for x in (g, r):
        assert REG.count_desk_register(x) == 0 and R.register_hits(x) == []


def test_R0923_a_REFUSED_report_cites_the_MENUS_OWN_address_and_only_when_the_menu_holds_it():
    """Item 4 / threat R-14: one document, one address. A refused report the turn's evidence menu
    holds prints the MENU's [E]; one the menu does not hold keeps HEAD's no-address row; nothing is
    minted and no chain seat is spent."""
    old = {"date": "2005-09-01", "source": "a crude report", "tier": 2, "source_key": "sk-crude-2005",
           "text": "crude oil prices pushed soybean oil demand for biodiesel"}
    hop = _hop(driver_id="crude_oil", lag_band=parse_lag("0-2 quarters"), receipts_top=(old,))
    ch = _chain([hop, _hop(driver_id="soybean_crush_margin")])
    ch.receipt_index = 0
    rp = R.chain_receipt(ch, None, asof=ASOF)
    assert rp["kind"] == "none" and rp["event_kind"] == "report_outside", rp
    assert rp["prop"]["source_key"] == "sk-crude-2005"
    # the menu holds it -> the menu's own [E]; the menu does not -> HEAD's no-address row
    assert R.chain_document_cite(rp, None, {"sk-crude-2005": 7}) == " [E7]"
    assert R.chain_document_cite(rp, None, {"sk-other": 3}) == ""
    assert R.chain_document_cite(rp, None, None) == ""
    # the EVENTS section's own handle still wins where it minted one (HEAD's rule, unchanged)
    assert R.chain_document_cite(rp, 4, {"sk-crude-2005": 7}) == " [E4]"
    row = R.sb_chain_document(rp, rp["hop"], cite_e=R.chain_document_cite(rp, None,
                                                                          {"sk-crude-2005": 7}))
    assert row.endswith("[E7].") and "outside the lag the model allows for it" in row, row
    assert R.classify(row) == ("SB-P",) and REG.count_desk_register(row) == 0
    assert "evidence_ordinals" in str(inspect.signature(R.render_board))
    assert "evidence_ordinals" in str(inspect.signature(S.fill_stage2))


def test_R0923_an_OFFSET_hop_cites_the_LAGGED_reading_AND_the_NEWEST_one():
    """THREAT_MODEL R-16: the palm board reads ONI at its declared six-month effect offset, and the chain
    hop on that row must never present the lagged reading as the current phase. The hop says "read six
    months back, the reading whose lag lands now" and cites the NEWEST reading's own handle beside the
    lagged one's. The fixture producer runs only the transform half (no newest reading), so the served
    producer's `recency["current_level"]` is supplied here the way `feeders.series_state` stamps it."""
    import types as _t
    from leviathan.graphrag import graph as _G
    from leviathan.graphrag.state import __main__ as _H
    from leviathan.graphrag.state import seam as _S
    base = _H.fixture_state_fn(_H.ASOF)

    def fn(ref, node):
        st, reads = base(ref, node)
        if st is not None and R._offset_applied(st):
            st.recency = dict(st.recency or {}, current_level=1.8, current_level_date="2026-08",
                              current_knowledge_date="2026-09-05")
        return st, reads

    g = _G.CausalGraph(_G.load_contracts(), silver=set(), version="harness")
    sg = _t.SimpleNamespace(seeds=["malaysian_crude_palm_oil_cme"], nodes=[], trace={})
    bd = _S.fill_stage1(graph=g, sg=sg, asof=_H.ASOF, mode="deep", query="where does palm oil stand now?",
                        state_fn=fn, named=("malaysian_crude_palm_oil_cme",))
    got = _S.fill_stage2(bd, graph=g, sg=sg, state_fn=fn, state_chain=True)
    calls = list(bd.calls or ())
    hops = [x for x in got["block"].split("\n") if x.startswith("  chain ") and "months back" in x]
    assert hops, "the palm board renders a chain hop on its offset ONI row"
    for x in hops:
        m = re.search(r"with the newest reading at \[N(\d+)\]", x)
        assert m, x[:300]
        c = calls[int(m.group(1)) - 1]
        assert c["rows"][0].get("stat") == "current_level", c
        lvl = re.search(r"^  chain [^\[]+\[N(\d+)\]", x)
        assert lvl and calls[int(lvl.group(1)) - 1]["rows"][0].get("offset_months") == 6, x[:200]


def test_fix_0923_RA_M1_the_hop_name_IS_the_rows_series_identity_basis_and_cell_rule_included():
    """09-23 FIX ROUND, review RA M1: one row reads ONE thing on its SB-1 line and on every chain line that
    cites it. The hop's printed name is its own row identity minus the date (`RowIdentity.series_words`):
    the card's BASIS rides it, and the read's CELL RULE rides it through the collapse the walk stamps on the
    hop (`ChainHop.collapse`) -- a single region cell is "one ... growing cell", a mean over cells says so,
    and a hop with no stamped collapse (a trace replay) prints the scope alone, never a guessed cell."""
    su = _hop(driver_id="psd_ending_stock_su_ratio",
              series_key="psd_ending_stock_su_ratio|soybeans_cbot|United States")
    assert R.chain_hop_name(su) == ("the stocks-to-use ratio, ending stocks as a share of domestic use, "
                                    "for United States")
    # 09-24 RE-BANK (CONTRACT K3, item 6): a region-cell read with NO collapse at a scope that is not one of
    # the producer's own aggregate surfaces names its SCOPE ALONE -- the round-1 "single_cell" default read
    # cocoa's West Africa BASIN MEAN as "one West Africa growing cell"; the rows prove no cell there.
    for collapse, tail in ((None, ", for United States"), ("", ", for United States"),
                           ("mean", ", for the mean over the United States growing cells")):
        h = _hop(driver_id="us_drought", series_key="drought_z|soybeans_cbot|United States", collapse=collapse)
        name = R.chain_hop_name(h)
        assert name.endswith(tail), (collapse, name)
        ident = R._hop_identity(h.contract, h.driver_id, h.series_key, R._hop_collapse(h))
        assert name == ident.series_words()
