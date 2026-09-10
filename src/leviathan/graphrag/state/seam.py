"""THE SERVING SEAM -- STATE ENGINE DESIGN sec 3.9 (where the board runs and how it FEEDS quantify),
sec 6.4 (the mandate), sec 6.7 (the decline tags), sec 10.5 (the counters). Sitting S6, phase 2.

WHAT THIS MODULE IS, AND WHY IT IS IN ``state/`` RATHER THAN IN ``answer.py``. Phase 2 wires the board
into the ONE function every quantifying turn runs (`_answer_l2`), and the wiring is about a hundred
lines of composition: anchors, two stages, the tape, the analogs, the watch rows, the age clauses, the
recency layers, the render, and a fail-closed belt around every one of them. Put in `answer.py` those
lines would sit inside the largest function on the serve path, inside the g1x seam golden's own
neighbourhood, and they could not be exercised without a subgraph, a planner and a model. Put HERE they
are two calls at the seam and a module the decks drive with injected fakes -- which is the same
separation `cascade.py` already keeps from `answer.py`, one layer up.

THE THREE LAWS THIS MODULE KEEPS, each measured rather than asserted:

  1. **IT NEVER RAISES.** Every public entry belts its whole body and returns the OFF shape on any
     failure -- `None` for a board, `{}` for the render. A board that breaks an answer is worse than no
     board, and the estate has the scar: the quantify seam's own `except Exception` (answer.py, "degrade
     to the QUALITATIVE mentor answer, never the floor") exists for the same reason one layer down.
  2. **IT READS NO ENVIRONMENT.** `GRAPHRAG_STATE_BOARD` is read ONCE per turn at the answer seam
     (`answer._state_board_on`) and threaded in -- the `GRAPHRAG_COMOVE` idiom, and the same rule
     `cascade.py` is pinned on (`"os.environ" not in src`).
  3. **IT IS OMIT-WHEN-OFF.** With the flag off the seam calls nothing here at all, so the board's cost
     on a flag-off turn is one boolean read, and `cascade.quantify` is byte-identical because the
     `board=` kwarg is ABSENT rather than None-valued.

THE TWO STAGES ARE TWO FUNCTIONS BECAUSE THEY RUN AT TWO SEAMS (D11). :func:`fill_stage1` runs after
`pl.grounded_subgraph` and before `pl.ground`; :func:`fill_stage2` runs after `ground` and before
`cq.quantify`, and it is the one that can read receipts, because `n.evidence` does not exist until
`ground` fills it. Both are on the calling thread, both are under the numbers pole on a hybrid turn at
p50, and both are additive on a pure reasoning turn -- which is what arm A measures with `ms_board`.

ASCII-ONLY; the file is UTF-8.
"""
from __future__ import annotations

import time
from typing import Optional

from leviathan.graphrag.state import board as B

#: The lane words sec 7 declares the board does NOT run on, in the orchestrator's own spelling. A lane
#: that is not here runs the board; a lane that is stamps `lane_off:<word>` so `BoardFired` is
#: absent-when-inapplicable (10.5) rather than a silent zero.
OFF_LANES: tuple = B.OFF_LANES

#: The lanes it DOES run on: `run_reasoning` and `run_hybrid`. Declared as a set so an unknown lane word
#: is a decline with its own name rather than an accidental fire.
#:
#: SEC 7 PUTS `run_live` IN THIS SET AND THIS BUILD TAKES IT OUT, as a DECISION with its own word rather
#: than a drift (S6 review, major 5). `run_live` is the declared D-AM-10 mode-threading exemption
#: (orchestrator: "it runs no grounded walk, no ground(), no response contract and no episode scaffold,
#: so every v1 knob is structurally inapplicable"), so a live turn reaches `_answer_l2` with
#: `mode_name=None`, resolves `standard`, gets `board_knobs_of('standard') is None` and declines
#: `lane_off:standard` -- a TIER word standing in for a LANE word inside a closed vocabulary, on a lane
#: the design says is ON. Leaving it declared-on made `ON_LANES`' third member dead code that reported
#: the wrong reason. The other remedy -- thread the mode into `run_live` -- would put the board's read
#: budget on the news lane and is a decision about which tier a live turn reads; it is a residual, not
#: this sitting's. `orchestrator._STATE_BOARD_OFF_INTENTS` stamps the live lane `lane_off:run_live` so
#: the census sees the exclusion by name.
ON_LANES: tuple = ("run_reasoning", "run_hybrid")


def lane_word(lane: Optional[str]) -> str:
    """The lane's own word, or `''` when the lane is one the board RUNS on (sec 7).

    A LANE NOBODY DECLARED IS OFF AND KEEPS ITS OWN NAME. Returning one of the four declared words
    for an unknown lane would put a lie in a closed vocabulary -- a census row saying `trivial`
    about a lane that is not the trivial router -- and returning `''` would run the board on a lane
    nobody adjudicated, which is fail-OPEN. The raw word rides the `lane_off:<detail>` tail, which
    is exactly what that tail is for, and the caller declines without ever entering the walk."""
    w = str(lane or "").strip()
    return "" if w in ON_LANES else (w or "unset")


# ---------------------------------------------------------------------------------------------------
# THE SUBJECT (SUBJECT RESOLVER D5 / D6 / D8) -- threaded, never read from the environment
# ---------------------------------------------------------------------------------------------------
def _subject_payload(subject) -> dict:
    """Normalise the threaded subject into ``{on, picked, hints, ambiguous}``. NEVER RAISES.

    TWO SHAPES ARE ACCEPTED AND THAT IS DELIBERATE, not laxity: the orchestrator threads a MAPPING
    (the planner's picks, the resolver's hint payload, the carried ambiguity), while a deck that only
    needs the anchor behaviour threads a bare sequence of ids. ``None`` -- every turn the flag does not
    reach -- yields ``on=False`` and an empty pick tuple, and every line downstream is then S6's own."""
    out = {"on": False, "picked": (), "hints": {}, "ambiguous": ()}
    if subject is None:
        return out
    try:
        if isinstance(subject, dict):
            picked = tuple(str(i) for i in (subject.get("picked") or ()) if str(i or "").strip())
            amb = tuple(str(i) for i in (subject.get("ambiguous") or ()) if str(i or "").strip())
            hints = dict(subject.get("hints") or {})
        else:
            picked = tuple(str(i) for i in (subject or ()) if str(i or "").strip())
            amb, hints = (), {}
    except Exception:                                   # noqa: BLE001 -- a malformed payload is OFF
        return out
    return {"on": bool(picked or amb or hints), "picked": picked, "hints": hints, "ambiguous": amb}


def _stamp_subject(bd, sub: dict, *, graph=None, focus_driver: str = "") -> None:
    """Write ``Board.subject`` (D8) and, where the turn earned it, the ``subject_ambiguous`` decline.

    THE AMBIGUITY IS CARRIED ON EVERY BOARD THAT HAS ONE, AND THE DECLINE IS TAKEN ONLY ON AN
    ANCHORLESS BOARD -- two states, and the restraint on the second is the point. A turn that anchored
    on markets the user named has an answer to give; replacing it with a question would be a fence that
    DELETES, which doctrine forbids. What that turn gets instead is the ambiguity on the board's own
    NOTES, which the S3 render mints as an SB-X row beside everything else it carries
    (``render.render_board``'s note loop -- and that branch had to be BUILT: for one build this note
    was appended into a loop that had no case for it, so the row reached nobody). An ANCHORLESS board
    would have declined ``anchor_none`` -- "the question named no market this estate tracks" -- and
    ``subject_ambiguous`` is strictly more informative about the same turn: it names the two drivers
    the phrase could mean and asks the reader to choose. That board renders NO ordinary block at all
    (``fill_stage2`` gates the whole render on ``bd.anchors``), so the seam mints the one row by hand
    rather than letting the more informative decline be the more silent one.

    AND THE CARRY HAS THREE CONDITIONS, NOT ONE (phase D, 2026-09-10). The planner must have returned
    NO subject (D5's own words, held here and at the orchestrator), the candidates must be worth a
    reader's interruption (:data:`state.subject.AMBIG_FLOOR`, one layer up), and NO FREE TIER MAY HAVE
    MATCHED THE PHRASE. The third is the one this build adds: a T0 or T1 hit means the planner was
    shown the driver by its own name and declined anyway, which is a decision rather than an
    ambiguity, and the estate's only measured carry (deck v2's dc23, a how-to-compute ask on a driver
    the phrase names outright) was exactly that shape. What the carry is fenced ON, and what it now
    de-duplicates BY, are two halves of one correction: ``SubjectHints.ambiguous()`` collapses a group
    to its strongest member, so ``len(amb) >= 2`` below counts DRIVERS and not spellings.

    THE IDS RIDE THE DETAIL TAIL AND THE TRACE, NEVER THE EMF DIMENSION: ``reason_dimension`` cuts at
    the colon precisely so an unbounded value cannot become a CloudWatch dimension, and two driver ids
    joined by a pipe is exactly that. Asserted in the deck rather than assumed."""
    if bd is None or not sub.get("on"):
        return
    try:
        picked = tuple(sub.get("picked") or ())
        amb = tuple(sub.get("ambiguous") or ())
        gm: dict = {}
        if picked and graph is not None:
            from leviathan.graphrag.state import subject as SUBJ
            gm = {p: list(SUBJ.expand_group((p,), graph)) for p in picked}
        fd = str(focus_driver or "")
        vs = ""
        if fd and picked:
            vs = "same" if fd in set(picked) | {i for v in gm.values() for i in v} else "differ"
        bd.subject = {"hints": dict(sub.get("hints") or {}), "picked": list(picked),
                      "groups": gm, "source": bd.anchor_source, "vs_focus": vs}
        # WHICH IDS EACH BOARD ACTUALLY ANSWERED UNDER -- `Anchor.group` READ, not merely written. The
        # field's stated purpose is "what lets the render and the trace say which name this board
        # answered under", and until this line nothing but the anchor collapse read it: the trace
        # carried the pick -> group map, which is a property of the SUBJECT, and never the per-board
        # intersection, which is a property of the BOARD (`fertilizer_input_costs` sits on eight boards
        # and `fertilizer_cost` on five).
        carried = {a.contract: list(a.group) for a in bd.anchors if a.source == "subject" and a.group}
        if carried:
            bd.subject["carried"] = carried
        # THE FREE-TIER DECLINE (phase D, 2026-09-10). A carry is D5's answer to "the phrase could
        # mean two drivers and the planner could not choose" -- and that reading only holds when the
        # candidates came from the SEMANTIC tier alone. When T0 or T1 matched the phrase, the planner
        # was shown the driver BY NAME and still returned nothing, which is a DELIBERATE DECLINE and
        # not an ambiguity: the how-to case is exactly this shape -- a desk types "crush margin"
        # literally, asks how the figure is COMPUTED, and the frozen block tells the planner to name
        # no subject. MEASURED on phase C, deck v2 row dc23: T0 exact-matched `crush_margin` and two
        # ids of that one family cleared AMBIG_FLOOR (0.7962 / 0.7803), so the estate's ONLY measured
        # carry was a row that would have asked the reader to choose after the planner had already
        # decided there was nothing to choose between. The v2 block's closure at the PICK was being
        # undone one layer down; this is the same closure at the carry.
        #
        # THE HINTS ARE THE WITNESS AND THEY ALREADY RIDE THE PAYLOAD (`SubjectHints.trace()` carries
        # `exact` and `alias`), so nothing new is threaded. A payload with no hints at all -- a deck's
        # short form -- reports no lexical hit and carries, which is the fail-open reading: absence of
        # evidence that a free tier fired is not evidence that one did.
        #
        # AND A HIT ON A FENCED ID COUNTS, WHICH IS A SCOPE AND NOT AN OVERSIGHT. A phrase that
        # word-matches `state.subject.OWN_STRUCTURE_IDS` was never SHOWN to the planner -- the enum
        # and the hint line both drop it -- so the "shown by name and declined" reading does not hold
        # for it. It declines the carry anyway, for the row's own sake rather than the planner's: a
        # desk that typed the board's own curve or its own cash-versus-board asked a MARKET-STRUCTURE
        # question, which the frozen block already tells the planner to name no subject for, and
        # answering it with "did you mean the soy-palm premium?" is the same decoy noise the enum
        # fence exists to kill -- one layer further out, at the row that STOPS A READER. MEASURED
        # across every banked layer-1 run of both decks and the held-out set (17 runs): 77 rows carry
        # a candidate at AMBIG_FLOOR and ZERO of them have a fenced-only lexical hit, so this clause
        # moves no banked number. It is stated because a rule whose reason and whose computation
        # disagree on a case nobody has met yet is a rule that will be read wrong when someone does.
        _lex = ()
        try:
            _h = sub.get("hints") or {}
            _lex = tuple(_h.get("exact") or ()) + tuple(_h.get("alias") or ())
        except Exception:                               # noqa: BLE001 -- a malformed hint dict is no hit
            _lex = ()
        if amb and not picked and _lex:
            # NOT DELETED, NAMED. The two ids stay on the trace through `hints` either way; what this
            # records is that the CARRY was declined and why, so a census can separate "no ambiguity"
            # from "an ambiguity a free-tier hit disqualified".
            bd.subject["ambiguous_declined"] = "lexical_hit"
            amb = ()
        if amb and not picked:
            # THE CARRY IS ITS OWN FACT AND IT IS RECORDED WHETHER OR NOT THE BOARD DECLINED, because
            # the render mints the row on both paths and a counter that could only fire on the
            # anchorless one would measure the rarer half of what a reader is shown.
            #
            # AND IT IS FENCED ON `not picked`, which is D5's own condition and was NOT in the code.
            # `SubjectHints.ambiguous()` is "what D5 CARRIES into the answer WHEN THE PLANNER RETURNS
            # NO SUBJECT", and the seam appended the note whenever the tuple was non-empty -- so a
            # turn where the planner DID choose, and the board therefore opened on that choice, would
            # still have stopped to ask the reader which of two drivers they meant. A question beside
            # an answered board is not more information, it is a contradiction: the block says "here
            # is El Nino on corn" and the row underneath says "name the one you mean". The two ids
            # stay on the TRACE either way through `hints`, so nothing is deleted -- only the row that
            # interrupts a reader is fenced, which is the AMBIG_FLOOR's own posture one layer up.
            bd.subject["ambiguous"] = list(amb[:2])
            bd.notes.append({"kind": "subject_ambiguous", "ids": list(amb[:2])})
        if not picked and len(amb) >= 2 and not bd.anchors:
            bd.stamp("board", "declined", reason="subject_ambiguous:" + "|".join(amb[:2]))
            bd.subject["declined"] = "subject_ambiguous"
    except Exception:                                   # noqa: BLE001 -- a board must never break a turn
        return


# ---------------------------------------------------------------------------------------------------
# STAGE 1 -- after `pl.grounded_subgraph`, before `pl.ground` (D11)
# ---------------------------------------------------------------------------------------------------
def fill_stage1(*, graph, sg, asof: str, mode: str, query: str = "", lane: str = "run_hybrid",
                qfn=None, state_fn=None, key_fn=None, turn_kind: str = "", legb_on: bool = False,
                attached_event: Optional[str] = None, focus_driver: str = "", named=(),
                max_contracts: int = 2, width: int = 2, alternative_rank: bool = False,
                pg_live: bool = True, recency_facts: bool = True, analog_reads: bool = False,
                subject=None):
    """Build the board and run STAGE 1. Returns a :class:`state.board.Board`, or ``None`` when the
    turn cannot carry one at all (no graph, no as-of, no subgraph).

    A DECLINE IS A BOARD, NEVER A ``None``. An off lane, an anchorless turn and a tier with no knobs
    all return a board carrying the leg stamps and their closed words, because the seam must be able to
    stamp `state_board` on the trace for those turns -- a `None` would make the three
    indistinguishable from "the flag was off", which is exactly the hole sec 6.7 exists to close
    (`rv_reading_decline` None on 12 of 12 because the leg was never REACHED on 10).

    ``named`` is the markets the QUESTION named (Amendment 2). They anchor on every tier and are never
    truncated by ``max_contracts``, which keeps its job for the seeds the planner INFERRED. The TOTAL
    anchor set is still bounded, by the tier's own ``BoardKnobs.max_anchors``, and the walk names what
    that cut dropped -- see its note there; without it one FE gesture put 35 DAGs on a Scan turn.

    ``recency_facts`` IS A COUPLING AND NOT AN OUTAGE (S6 review). The board's SB-L rows and the
    mandate's closing sentence contradict `_SYSTEM_RECENCY_EDGE`, the shipped persona clause that dates
    the whole answer by one layer; S5 shipped the replacement behind its own dark flag. With the board
    on and that flag off the writer is handed both sentences AND three candidate edges to pick the
    oldest of, so the board makes the defect it was meant to close WORSE. The caller threads
    `answer._recency_facts_on()` and a False declines by name rather than shipping the pair.

    ``analog_reads`` states whether THIS caller wires an analog producer (`benchmark_fn` /
    `receipt_fn` at stage 2). It defaults FALSE here because the serving seam wires neither, and a
    reserved seat no producer can spend is a read on the walk's ceiling that nothing can ever pay --
    the leg-B rider, one column pair over (design 3.8; S6 review, major 7).

    ``subject`` (SUBJECT RESOLVER D6) is the turn's resolved subject, threaded as an ARGUMENT for the
    same reason `focus_driver` and `recency_facts` are -- ``check_state_seam`` clause (i) allows
    exactly ONE environment name across this package, so the flag is read once at the answer seam.
    It is a MAPPING ``{picked, hints, ambiguous}`` or a bare sequence of ids (the deck's short form);
    ``None`` is absent and every line below is then the S6 build's own, character for character.

    THE PICKS ANCHOR AND THE AMBIGUITY DECLINES, and they are two different states. Picks expand to
    their groups and anchor; an ambiguity the PLANNER declined to resolve anchors nothing and stamps
    ``subject_ambiguous`` with the two ids on its detail tail, so the render can name them and ask."""
    try:
        from leviathan.graphrag.state import walk as W

        asof_s = str(asof or "")[:10]
        if graph is None or not asof_s:
            return None
        off = lane_word(lane)
        # THE MIRROR'S OWN WORD (6.7's `pg_not_live`), and it is the CALLER's fact rather than
        # this module's: `answer._pgnumbers_live()` is the estate's one producer of it and it is
        # already read at the quantify seam, so it is threaded rather than re-derived. Without
        # this branch a mirror that is down would decline every ROW as `read_error` and the board
        # would report a coverage failure for what is a reader outage -- two different facts, and
        # only one of them is about the record.
        if not pg_live and state_fn is None:
            off = off or "pg_not_live"
        # THE RECENCY COUPLING, read BEFORE the lane branch so one decline shape carries all three
        # non-lane words. It is checked after `pg_not_live` because a mirror outage is the stronger
        # fact: a turn that could not read is not a turn whose recency grammar mattered.
        if not recency_facts:
            off = off or "recency_facts_off"
        if off:
            # THE OFF LANE DECLINES WITHOUT ENTERING THE WALK, and that is the fail-CLOSED
            # direction. `walk()` declines only for a lane in its own closed `OFF_LANES`, so an
            # UNDECLARED lane word threaded into it would fall through and RUN the board on a lane
            # nobody adjudicated. The board is built and stamped here instead: every leg
            # `not_reached` (a leg cannot stamp its own absence) and `board` declined with the
            # lane's own name on the `lane_off:<detail>` tail.
            bd = B.Board(asof=asof_s, mode=mode, knobs=B.board_knobs_of(mode),
                         graph_version=getattr(graph, "version", None), turn_kind=turn_kind)
            bd.stamp_not_reached(*W.ALL_LEGS)
            bd.stamp("board", "declined",
                     reason=off if off in ("pg_not_live", "recency_facts_off")
                     else f"lane_off:{off}")
            return bd
        _sub = _subject_payload(subject)
        anchors = W.resolve_anchors(
            contracts=[c for c in (getattr(sg, "seeds", None) or []) if c],
            named=tuple(named or ()), attached_event=attached_event,
            focus_driver=str(focus_driver or ""), graph=graph,
            max_contracts=max(0, int(max_contracts or 0)),
            positioning_ids=_positioning_ids(),
            # OMIT-WHEN-OFF ONE LAYER DOWN: with no subject this is `()` and `resolve_anchors` takes
            # the branch it took at S6, so the anchor set is the S6 build's own on every turn the
            # resolver did not reach.
            subject=_sub["picked"])
        # THE LANE IS THREADED, not re-spelled. It was a literal `"run_hybrid"` here while the caller's
        # real lane arrived at :66 and was read only by the off-lane test above -- a threaded fact
        # overwritten by a constant, inert today only because `Board.trace()` carries no lane field and
        # every off lane has already returned.
        bd = W.walk(graph=graph, asof=asof_s, mode=mode, anchors=anchors, question=query or "",
                    state_fn=state_fn or _state_fn(asof_s, qfn=qfn, turn_kind=turn_kind),
                    key_fn=key_fn, receipts=None, turn_kind=turn_kind,
                    lane=str(lane or "run_hybrid"),
                    knobs=B.board_knobs_of(mode), width=width, legb_on=legb_on,
                    alternative_rank=alternative_rank, stage2=False,
                    analog_reads=bool(analog_reads))
        _stamp_subject(bd, _sub, graph=graph, focus_driver=str(focus_driver or ""))
        return bd
    except Exception:                                   # noqa: BLE001 -- a board must never break a turn
        return None


# ---------------------------------------------------------------------------------------------------
# STAGE 2 -- after `pl.ground`, before `cq.quantify` (D11)
# ---------------------------------------------------------------------------------------------------
def fill_stage2(bd, *, graph, sg=None, qfn=None, state_fn=None, key_fn=None, legb_on: bool = False,
                width: int = 2, complexes=(), chains=(), benchmark_fn=None, receipt_fn=None,
                record_through: str = "", n_start: int = 1, e_start: int = 1) -> dict:
    """Run STAGE 2, then the analogs, the watch rows and the RENDER. Returns the seam payload:

    ``{"block": str, "request": dict, "trace": dict, "counters": dict, "recency": dict}``

    -- ``block`` is the STATE OF THE WORLD text (empty when the board declined, which is the same thing
    as "no marker in the volatile prompt", which is the same thing as "no mandate": ONE fact, read by
    one gate). ``request`` is :meth:`Board.request`, the `board=` payload. ``trace`` is the
    `state_board` key's payload. ``counters`` is 10.5's EMF block, absent-when-inapplicable.

    THE RECEIPTS COME FROM THE SUBGRAPH THE TURN ALREADY GROUNDED, never from a second retrieval: the
    board's only evidence-pool traffic is the counted analog receipt read (sec 3.9), and a per-row
    retrieval here is exactly the over-commitment revision 1 shipped and revision 2 withdrew (2.2).

    ``n_start`` / ``e_start`` ARE THE TURN'S HANDLE ORIGINS, and threading them is a correctness
    fix rather than a nicety. ``n_start`` continues the ``[N]`` count so the board's rows and the
    cascade's rows share ONE address space (6.3), and ``e_start`` continues the ``[E]`` count past
    the turn's own deduped evidence menu, which ``citations.unify`` numbers positionally from 1 --
    a board event receipt printing ``[E1]`` would point a reader at somebody else's document.

    ONE BOUNDARY IS DECLARED RATHER THAN DISCOVERED: an ``[E]`` the board mints resolves to a
    receipt that is NOT in the turn's own evidence list, because phase 2 feeds ONLY quantify and
    the text half is phase 3's (9.2). A writer copying such a handle loses the sentence to the
    verifier's ordinary unresolved-handle rule -- a STRIP, never a false claim, and never a
    collision now that the origins are threaded. Phase 3 admits the board's receipts into the
    turn's own list and closes it; until then the residual is named here and measured by the arm."""
    try:
        from leviathan.graphrag.state import analogs as A
        from leviathan.graphrag.state import narration as N
        from leviathan.graphrag.state import render as R
        from leviathan.graphrag.state import walk as W
        from leviathan.graphrag.state import watch as WA
        from leviathan.graphrag.state.rows import status_word

        if bd is None:
            return {}
        t0 = time.perf_counter()
        _render_ms = 0.0
        if bd.knobs is not None and bd.anchors and bd.stage_done.get(1):
            W.stage2(bd, graph, state_fn=state_fn or _state_fn(bd.asof, qfn=qfn,
                                                               turn_kind=bd.turn_kind),
                     key_fn=key_fn, receipts=_receipts_from(sg), width=width, legb_on=legb_on,
                     complexes=complexes, chains=chains,
                     analog_reads=bool(benchmark_fn is not None or receipt_fn is not None))
            _attach_tape(bd, qfn=qfn, width=width)
            ana = A.analog_rows(bd, knobs=bd.knobs, benchmark_fn=benchmark_fn, receipt_fn=receipt_fn)
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
            rec = N.recency_rows(bd, record_through=record_through, tape_edge=_tape_edge(bd))
            # THE RENDER IS TIMED SEPARATELY because it is the POLE. MEASURED warm, zero network, on
            # the builder's own `fixture_state_fn`: 238-3,295 ms, i.e. 60-92% of the board's whole
            # wall. Sec 3.9 wants `ms_board` beside `timing_ms.fill / rest / numbers` "so the pole is
            # identified per turn", and a counter that could not see the largest part of the board
            # would identify the wrong one.
            _tr = time.perf_counter()
            # `receipts_by_row=None` IS A DECLARED RESIDUAL, NOT AN OVERSIGHT (S6 review). The per-row
            # SB-R class and `BoardKnobs.render_receipts` therefore have no consumer on the SERVED path
            # -- `state/__main__.py` does the same, so the seam and the harness agree, and the receipt
            # cut this sitting swept fires on neither. The rows the turn grounded ARE available
            # (`_receipts_from(sg)`, already threaded into `W.stage2`), so wiring it is one argument;
            # it is held because the block is measured at 2.5-3.0x its sec 7 budget already and phase 3
            # is the sitting that decides which slices are READ. Named here so the swept cut's own note
            # is not read as a description of what a reader sees today.
            blk = R.render_board(bd, analogs=ana, watch=wr, receipts_by_row=None, recency=rec,
                                 age_clauses=ages, start=max(1, int(n_start)),
                                 e_start=max(1, int(e_start)),
                                 anchor_label=", ".join(R.board_label(s) for s in bd.anchor_slugs))
            _render_ms = (time.perf_counter() - _tr) * 1000.0
            # THE RENDER'S DECLINE WORD MEANS "A LINE WAS CORRECTED", NOT "NO BLOCK" (S6 review). The
            # register fence is PER LINE: a trip replaces the offending line with its own SB-X and the
            # block ships whole (`render_board`'s own law -- fences correct or compute, never delete).
            # A census reading `render: declined` as an absent block would over-count the failure by
            # every turn on which one composed line was fenced, so the count of trips rides the stamp.
            bd.stamp("render", "fired" if not blk.trips else "declined",
                     reason="template_register_trip" if blk.trips else "",
                     reads=len(blk.trips) if blk.trips else 0)
            text = blk.text()
            calls = list(blk.calls)
        else:
            ana, wr, rec, text, calls = [], [], {}, "", []
            # THE ONE BLOCK A DECLINED BOARD MAY MINT (SUBJECT RESOLVER D5), and it exists because the
            # two halves of that decision landed on opposite sides of this gate. `_stamp_subject` takes
            # the `subject_ambiguous` decline ONLY on an anchorless board -- the restraint is right, a
            # board with markets to talk about must not be replaced by a question -- and this gate
            # renders NOTHING without anchors. So the ONE board that could stamp the word was the one
            # board guaranteed to produce no reader text, and D5's "the block's absence row says, in
            # reader words, that the question may mean <name a> or <name b> and asks the reader to name
            # one" held for nobody. It is minted through `render.Block` rather than as a bare string so
            # the register fence grades it like every other row: a row that trips is CORRECTED, and a
            # row whose whole content is two driver display names is exactly the class
            # `register.internal_leaks` exists to grade.
            _sj = getattr(bd, "subject", None) or {}
            if _sj.get("declined") == "subject_ambiguous" and _sj.get("ambiguous"):
                _b = R.Block(start=max(1, int(n_start)), e_start=max(1, int(e_start)))
                _b.add(R.sb_subject_ambiguous(_sj.get("ambiguous") or ()), label="subject ambiguous")
                text, calls = _b.text(), list(_b.calls)
        # THE SEAM'S OWN WALL WINS, and the first build's `or` discarded it (S6 review, major 11).
        # `walk._stage2` has already stamped slot 2 with the time IT spent, so `x or y` kept the inner
        # number and threw away the measurement that includes the tape read, the analogs, the watch
        # rows, the age clauses, the recency ledger and THE RENDER -- MEASURED under-reporting the
        # board's wall by 8-17x (1 anchor quick 259 ms total vs MsBoard 15; 35 anchors deep 4,843 vs
        # 810). `max` rather than assignment so a caller that stamped a LARGER outer measurement of its
        # own is never lowered by this one; the two stages stay two numbers, and slot 2 now means "the
        # stage-2 seam's wall", which is what the counter has to publish to be an instrument.
        bd.stage_ms[2] = max(float(bd.stage_ms.get(2) or 0.0),
                             (time.perf_counter() - t0) * 1000.0)
        bd.stage_ms["render"] = _render_ms
        bd.calls = calls
        req = bd.request()
        cnt = counters(bd, block=text, analogs=ana, watch=wr, render_ms=_render_ms)
        tr = bd.trace()
        # THE COUNTERS RIDE THE TRACE, so `respond()`'s telemetry block EMITS what the turn
        # MEASURED rather than re-deriving it from a board it no longer holds. One producer for
        # the dashboard and the artifact is the whole of 'absent is never zero' being checkable.
        tr["counters"] = cnt
        # THE `board=` PAYLOAD IS RETURNED ONLY BY A BOARD THAT FIRED, so "the kwarg is absent"
        # and "the board produced nothing" are ONE fact rather than two that could disagree. A
        # declined board's request would carry an empty order, empty windows and no calls -- every
        # consumer would take HEAD's branch anyway -- but the CALL SITE would still read as a fed
        # turn in a diff and in a census, which is the kind of near-truth this seam cannot afford.
        # The TRACE is returned either way: a decline is exactly what the census must be able to
        # see (6.7), and that is the asymmetry, stated rather than implied.
        # AND "THE BOARD PRODUCED NOTHING" INCLUDES "NO BLOCK REACHED THE READER". The first build
        # gated the payload on the LEG alone, so a board whose leg fired while its render produced no
        # text would still FEED quantify -- node order, anchor windows and appended [N] rows -- on a
        # turn where the writer met no block and no mandate. That is two facts, not one, and the note
        # above claims one (S6 review). Both legs now.
        fired = ((bd.legs.get("board") or {}).get("outcome") == "fired") and bool(text)
        return {"block": text, "request": (req if fired else None), "trace": tr,
                "counters": cnt, "recency": rec, "analogs": ana, "watch": wr}
    except Exception:                                   # noqa: BLE001 -- a board must never break a turn
        return {}


# ---------------------------------------------------------------------------------------------------
# THE COUNTERS (sec 10.5) -- absent-when-inapplicable, never a fake zero
# ---------------------------------------------------------------------------------------------------
def counters(bd, *, block: str = "", analogs=(), watch=(), render_ms: float = 0.0) -> dict:
    """10.5's EMF block for ONE turn. Every value is a plain int and every key is OMITTED when the turn
    cannot measure it -- ABSENT IS NEVER ZERO, the same contract `_cw_turn_spent` keeps one layer down.

    `BoardFired` is 0/1 and is present whenever the board RAN (including a decline, which is a measured
    zero); on a turn where the flag was off nothing calls this at all, so the metric has no population
    to dilute."""
    if bd is None:
        return {}
    legs = bd.legs or {}
    board_leg = legs.get("board") or {}
    fired = 1 if board_leg.get("outcome") == "fired" else 0
    out: dict = {"BoardFired": fired}
    _subj = _subject_counters(bd)
    if not fired:
        # THE DECLINED HALF IS A MEASURED ONE, under the `reason` dimension 10.5 gives this counter.
        out["BoardDeclined"] = 1
        out.update(_subj)                               # a DECLINED board still measured its subject
        return out
    from leviathan.graphrag.state.rows import status_word

    # THE FOUR LEDGER COUNTERS ARE READ, NEVER RE-DERIVED -- and `BoardEvidenceBorrows` had to be
    # REPAIRED at the producer rather than here (S6 review, major 6): the walk assigned it the RESERVED
    # analog-receipt seats, so this line published 3 on every fired Analysis board and 5 on every fired
    # Cascade board while `analogs._receipts_for` returned [] at zero reads. The counter's own 10.5
    # definition is "analog receipt reads on the evidence pool"; it is now counted where a borrow
    # happens, and the SEATS are `Ledger.evidence_cap`, which is what a reserved seat is.
    # `BoardPoolDeclined`, `BoardEvidenceBorrows`,
    # `BoardReplayLabelled` and `BoardBudgetCapped` all have exactly one producer (`state/walk.py`'s
    # two waves and `render.attach_tape`), and a second derivation here would be a counter that agrees
    # with the ledger until the day a walk edit moves one of them -- the drift class this estate has
    # measured three times. The two that have NO ledger field (`BoardStateRows`,
    # `BoardTextOnlyRows`) are counted off the rows, which is where they live.
    led = bd.ledger
    out["BoardStateRows"] = sum(1 for r in bd.rows
                                if r.state is not None and status_word(r.state.status) == "ok")
    out["BoardTextOnlyRows"] = sum(1 for r in bd.rows
                                   if (r.state is None or status_word(r.state.status) != "ok")
                                   and (r.receipts or {}).get("n"))
    # 10.5 GIVES `BoardDeclined` THE `reason` DIMENSION, i.e. it is about the BOARD's own decline, and
    # the first build emitted a count of declined LEGS under it -- so a FIRED board contributed a
    # non-zero `BoardDeclined` at `reason=none` and the dashboard's declined series mixed two
    # populations (S6 review). `BoardDeclined` is now the board's own 0/1, which is what the dimension
    # describes, and the leg count keeps its own name.
    out["BoardDeclined"] = 0
    out["BoardLegsDeclined"] = sum(1 for k, v in legs.items()
                                   if k != "board" and (v or {}).get("outcome") == "declined")
    out["BoardReads"] = int(bd.net_reads())
    # 10.5 GIVES `BoardReads` THE `wave` DIMENSION. It is emitted as THREE NAMED COUNTERS on the one
    # record instead, and that is a deliberate cardinality decision rather than a drift: the EMF block
    # is already dimensioned (mode x reason), a `wave` dimension would require a SECOND record per wave
    # and triple this line's monthly bill for a split that has exactly three known values. Named
    # counters give the dashboard the same split at one third of the cardinality.
    _w = bd.ledger.waves
    out["BoardReadsWave1"] = int((_w.get(1).reads_used if _w.get(1) else 0) or 0)
    out["BoardReadsWave2"] = int((_w.get(2).reads_used if _w.get(2) else 0) or 0)
    out["BoardReadsTape"] = int(led.tape_reads)
    out["BoardBudgetCapped"] = int(led.budget_capped)
    out["BoardAnalogs"] = sum(1 for a in analogs or () if not a.get("declined"))
    out["BoardWatchLines"] = len(watch or ())
    out["BoardPoolDeclined"] = int(led.pool_declined)
    out["BoardEvidenceBorrows"] = int(led.evidence_borrows)
    out["BoardReplayLabelled"] = int(led.replay_labelled)
    out["BoardTruncated"] = sum(
        1 for r in bd.rows
        if r.state is not None and status_word(r.state.status) == "history_truncated")
    ms = (bd.stage_ms.get(1) or 0.0) + (bd.stage_ms.get(2) or 0.0)
    if ms:
        out["MsBoard"] = int(ms)
    _rms = float(render_ms or bd.stage_ms.get("render") or 0.0)
    if _rms:
        # THE POLE, NAMED. The render is 60-92% of the board's measured wall and `MsBoard` alone could
        # not see it, so arm A would have attributed the board's cost to its reads (sec 3.9).
        out["MsBoardRender"] = int(_rms)
    if block:
        out["BoardBlockChars"] = len(block)
    out.update(_subj)
    return out


def _subject_counters(bd) -> dict:
    """The SUBJECT RESOLVER's four counters (D8), ABSENT-WHEN-INAPPLICABLE like every other key here.

    NO NEW EMF RECORD AND NO NEW DIMENSION. They ride the board's own record at
    ``orchestrator.py:2607-2621``, whose ``units`` line types any ``Ms``-prefixed key as Milliseconds
    automatically -- which is why the timer is ``MsBoardSubject`` and not ``SubjectMs``. On a turn the
    resolver did not run, ``Board.subject`` is empty and this returns ``{}``, so the metrics have no
    zero-population to dilute and a census can tell "off" from "ran and found nothing"."""
    sj = getattr(bd, "subject", None) or {}
    if not sj:
        return {}
    hints = sj.get("hints") or {}
    picked = sj.get("picked") or []
    out: dict = {}
    if picked:
        out["BoardSubjectResolved"] = 1
    # THE COUNTER MEASURES WHAT A READER WAS SHOWN, and the render mints the SB-X row on BOTH paths --
    # the anchorless decline and the ambiguity carried beside an anchored board's own rows. Gating this
    # on `declined` alone published the rarer half: an ambiguity on an ANCHORED board rendered a row
    # and emitted no counter at all, so the metric and the block disagreed by construction on the more
    # common of the two states.
    if sj.get("ambiguous") or sj.get("declined") == "subject_ambiguous":
        out["BoardSubjectAmbiguous"] = 1
    # A DECLINED TIER IS ITS OWN MEASUREMENT, and it is the one the deploy gate cares about: `stale`
    # and `missing` are the two words that mean the shipped artifact and the shipped graph disagree.
    if str(hints.get("vocab_status") or "") in ("missing", "stale", "unreadable"):
        out["BoardSubjectDeclined"] = 1
    # A LITERAL ZERO IS NOT A MEASUREMENT ANYONE CAN AGGREGATE, and that is why this key is ABSENT
    # below a millisecond rather than published as 0. `orchestrator.py:2619` types every `Ms`-prefixed
    # key as MILLISECONDS, so a published 0 does not enter CloudWatch as "under half a millisecond" --
    # it enters as a zero-latency SAMPLE, and a p50 built from a population of them says the resolver
    # is free on turns where it in fact ran and took 0.4 ms. Absence costs nothing here because the
    # timer is never the only witness that the tier ran: `BoardSubjectResolved`, `BoardSubjectDeclined`
    # and `Board.trace()["subject"]["hints"]["ms"]` all still say so, and the trace keeps the fraction
    # this key cannot carry. It is also `MsBoard`'s own idiom in this same function, applied here.
    _ms = hints.get("ms")
    if isinstance(_ms, (int, float)) and int(float(_ms)) >= 1:
        out["MsBoardSubject"] = int(float(_ms))            # `int(ms)`, this file's own convention
    return out


# ---------------------------------------------------------------------------------------------------
# the injected seams' PRODUCTION halves
# ---------------------------------------------------------------------------------------------------
def _state_fn(asof: str, *, qfn=None, turn_kind: str = ""):
    """``(ref, node) -> (StateRow, reads)`` over the pg mirror, on the NUMBERS bulkhead.

    THE BOARD OPENS ITS OWN READER AND THE TURN'S `numbers_lookup` DOES NOT STEER IT. That is D20 and
    it is correct -- see the paragraph below -- but it has a consequence worth stating where a reader
    of this module will meet it: an eval or offline arm that injects `numbers_lookup` to control the
    turn's numbers steers `cascade.quantify` and NOT the board. Such an arm needs its own injection
    point, and it has one -- `fill_stage1(qfn=)` / `fill_stage2(qfn=)`, which every deck in
    `test_state_seam.py` uses -- but nothing said so until the S6 review asked.

    ``qfn`` defaults to :func:`feeders.board_query_fn` -- `pgnumbers.pg_query` wrapped so a pool wait
    or a statement timeout declines BY NAME. NEVER `pgnumbers.query_fn`: its per-request Athena
    fallback would turn a board read into the two-minute wall the mirror exists to remove, and its
    borrow counter is lane-wide, so the fallback could not even be attributed to the board (D20)."""
    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state.lint import load_conventions

    executor = qfn if qfn is not None else F.board_query_fn()
    try:
        conv = dict(load_conventions() or {})
    except Exception:                                   # noqa: BLE001 -- an unreadable config declines
        conv = {}
    windows = dict(conv.get("windows") or {})
    blocks = dict(conv.get("conventions") or {})

    def _fn(ref, node):
        st = F.series_state(ref, node, asof, qfn=executor, windows=windows, conventions=blocks,
                            turn_kind=turn_kind)
        return st, int(getattr(st, "reads", 0) or 0)
    return _fn


def _attach_tape(bd, *, qfn=None, width: int = 2) -> None:
    """The anchor boards' SB-T rows -- ONE mirror read per anchor (D19). A board with no tape slug
    stamps its own closed word; the leg is stamped either way, so `not_reached` never stands in for a
    decline the tape actually made.

    **PRICED BEFORE THE FETCH, AND CONCURRENT (S6 review, major 10).** The first build looped the
    anchors serially on the calling thread and let `render.attach_tape` set `tape_cap` AFTERWARDS from
    the tape it was handed -- a post-hoc record of the spend wearing the word "cap", in the one column
    `WaveLedger.priced_before_fetch` and `Board.rectangle` do not cover. Design 3.8's law is "cut EACH
    wave at its cap BEFORE its fetch ... every dropped key is NAMED", and the S6 ceiling comment one
    layer down says the same thing in its own words ("THE CAP, NEVER THE SPEND"). `render.price_tape`
    declares the seats and names the boards it cannot afford; the reads then run at the board's own
    width, like both waves, instead of paying 100-300 ms serially per anchor on the serve path."""
    from concurrent.futures import ThreadPoolExecutor

    from leviathan.graphrag.state import feeders as F
    from leviathan.graphrag.state import render as R

    executor = qfn if qfn is not None else F.board_query_fn()
    slugs = R.price_tape(bd)                            # THE CAP, BEFORE THE FETCH

    def _one(slug):
        try:
            return slug, F.tape_state(slug, bd.asof, qfn=executor)
        except Exception:                               # noqa: BLE001 -- one board's tape, never the turn
            return slug, None

    tape, reads = {}, 0
    if slugs:
        with ThreadPoolExecutor(max_workers=max(1, min(int(width or 1), len(slugs)))) as pool:
            got = list(pool.map(_one, slugs))
        for slug, tp in got:
            if tp is not None:
                tape[slug] = tp
                reads += int(getattr(tp, "reads", 0) or 0)
    if tape:
        # `reads_each=0` and then the MEASURED total, because D19's "one mirror read per anchor board"
        # is the SEAT and `tape_state`'s own `reads` is the SPEND -- a declined tape spends none, and a
        # ledger that recorded the seat as the spend would over-count the board's own budget term.
        R.attach_tape(bd, tape, reads_each=0)
        bd.ledger.tape_reads += int(reads)
    bd.stamp("tape", "fired" if tape else "declined",
             reason="" if tape else "no_tape_slug", reads=int(reads))


def _tape_edge(bd) -> str:
    """The newest session on any anchor's tape -- the ledger's THIRD layer (6.5 (2)). Empty when the
    turn read no tape, which the ledger states as words rather than as a blank."""
    return max((str(getattr(t, "level_date", "") or "") for t in (bd.tape or {}).values()),
               default="")


def _receipts_from(sg) -> dict:
    """``{(contract, driver_id): [receipt dicts]}`` from the subgraph `ground()` already filled.

    THIS IS THE WHOLE OF THE BOARD'S TEXT INPUT IN PHASE 2, and its cheapness is the point: `ground`
    has already paid for `n.evidence`, so the board's text tier costs zero reads. Phase 3 is where the
    board decides which slices are READ; phase 2 only reads what the turn already has."""
    out: dict = {}
    for n in (getattr(sg, "nodes", None) or []):
        ev = getattr(n, "evidence", None) or []
        if not ev:
            continue
        key = (getattr(n, "contract", None), getattr(n, "id", None))
        if not key[0] or not key[1]:
            continue
        out.setdefault(key, []).extend(dict(h) for h in ev if isinstance(h, dict))
    return out


def _positioning_ids() -> tuple:
    """The positioning driver ids, for Amendment 1's `subject` exception. Read from the cascade map's
    own positioning tables so this module declares no second roster."""
    try:
        from leviathan.graphrag.state import feeders as F
        casc = F._casc()
        pos = set(getattr(casc, "POSITIONING_TABLES", ()) or ())
        return tuple(sorted(ref for ref, row in (F.board_map() or {}).items()
                            if (row or {}).get("table") in pos))
    except Exception:                                   # noqa: BLE001 -- no roster is not an error here
        return ()


def reason_dimension(reason: Optional[str]) -> str:
    """The EMF `reason` dimension for a declined board: the CLOSED WORD, never a slug (10.5).

    A parametrised word is cut at its colon (`lane_off:numbers_only` -> `lane_off`,
    `thin_history:3` -> `thin_history`) because the detail is a COUNT or a LANE NAME, and either
    of them as a CloudWatch dimension value is an unbounded cardinality bill on a metric nobody
    can then aggregate. A board that FIRED reports `none`, which is a member of the dimension
    rather than an absence -- a missing dimension value would silently merge the fired and
    declined populations into one series."""
    w = str(reason or "").split(":", 1)[0].strip()
    if not w:
        return "none"
    return w if w in B.BOARD_REASONS else "other"


__all__ = ["fill_stage1", "fill_stage2", "counters", "lane_word", "reason_dimension",
           "ON_LANES", "OFF_LANES"]
