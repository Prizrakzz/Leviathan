"""THE WALK -- STATE ENGINE DESIGN sec 3 whole. Sitting S2.

  3.1 the anchor (incl. sec 16's AMENDED grammar: named markets are ALL anchors, a `focus_driver`
      anchors every contract carrying it, cold start is `board_loudest` over a PRICED read set, a
      user-named `near` is analog candidate one, and the asked horizon is parsed by ONE closed regex)
  3.2 loudness -- the D2 rank tuple, the banked alternative, band-crossers and open events
  3.3 the order of operations -- TWO stamped stages, no replan, no agent loop
  3.4 upstream and downstream inside the anchor DAG -- the FULL ancestor closure, render cap only
  3.5 inter-commodity edges, complexes, chains, convergence as ORDERING WORDS
  3.6 the shared-driver fan-out -- every far board NAMED at zero reads, far states priced by `fan_k`
  3.7 dated events stay on the board and project forward until their band expires
  3.8 the read budget -- two waves, each priced BEFORE its fetch, atomic, both rectangles closed
  3.9 the `board_request` shape S6 threads into `quantify` (built in `board.py`; nothing here touches
      `cascade.py`)

THE ONE SENTENCE THIS MODULE IS. The query picks the ANCHOR and nothing else; the GRAPH decides what is
relevant; every node of every touched board is a ROW; the sign is read off the EDGE at traversal and is
never reconciled; the budget is priced before the fetch and every dropped key is NAMED; and every leg
says `fired` / `declined:<reason>` / `not_reached` from a closed vocabulary.

WHAT IS DELIBERATELY ABSENT, so each is a decision rather than a gap:
  * NO REPLAN. Stage 2 never re-ranks stage 1; it APPENDS (sec 3.3). There is no loop in this file that
    re-enters a stage, and no branch anywhere that consults an outcome to decide what to read next
    beyond the ONE dependency the design licenses: wave 2 is priced from the wave-1 rank.
  * NO THRESHOLD ANYWHERE (ruling 1). Nothing here drops a row for being quiet. `loud_k` is a RANK CUT
    that decides what fans and what orders convergence; every row below it is on the board, is rendered
    when the budget allows, and is NAMED when it is not.
  * NO ENVIRONMENT READ. Every knob is threaded (the `GRAPHRAG_COMOVE` idiom); the executor, the state
    producer and the clock are INJECTED, which is what lets every deterministic bar of sec 10.2 run on
    fixture arrays with no pg mirror.
  * NO SUMMED LAG BAND. A path's band is never summed (doctrine M-4); `LagBand.__add__` refuses at
    runtime and `state/lint.py` greps this package for the arithmetic.

ASCII-ONLY on anything this module prints; the file is UTF-8.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple, Optional

from leviathan.graphrag.state import board as B
from leviathan.graphrag.state.lagbands import QUARTER_MONTHS, LagBand, parse_lag
from leviathan.graphrag.state.rows import SIGN_WORDS, StateRow, status_word

# ---------------------------------------------------------------------------------------------------
# 3.1 THE ASKED HORIZON -- ONE closed regex, and it anchors nothing
# ---------------------------------------------------------------------------------------------------
#: The design's own regex, verbatim (sec 3.1): `(\d+|one|two|three|six|twelve)\s*(month|quarter|year)s?`.
#: A horizon ANCHORS NOTHING and SELECTS NOTHING -- it feeds ONE clause of SB-J ("the horizon asked
#: about, {n words} months, sits {inside | before | past} that window") as board month-arithmetic. This
#: is the one job the query keeps beyond naming the anchor, and it is a parse rather than a guess.
HORIZON_RE = re.compile(r"\b(\d+|one|two|three|six|twelve)\s*(month|quarter|year)s?\b", re.IGNORECASE)

_HORIZON_WORDS: dict = {"one": 1, "two": 2, "three": 3, "six": 6, "twelve": 12}
_HORIZON_UNIT_MONTHS: dict = {"month": 1, "quarter": QUARTER_MONTHS, "year": 12}


def parse_horizon(question: Optional[str]) -> Optional[int]:
    """The asked horizon in MONTHS, or ``None`` when the question asks for none.

    FIRST MATCH WINS, and that is the deterministic reading rather than the clever one: a question with
    two horizons ("over three months, versus the last two years") is a question whose FIRST horizon is
    the one asked about and whose second is a comparison window, and a board that silently picked the
    larger would print a projection clause about a span nobody asked for. One regex, one match, one
    number -- and ``None`` when the regex does not fire, which the render says nothing about at all."""
    m = HORIZON_RE.search(question or "")
    if not m:
        return None
    n_raw, unit = m.group(1).lower(), m.group(2).lower()
    n = _HORIZON_WORDS.get(n_raw)
    if n is None:
        try:
            n = int(n_raw)
        except ValueError:
            return None
    if n <= 0:
        return None
    return n * _HORIZON_UNIT_MONTHS[unit]


# ---------------------------------------------------------------------------------------------------
# 3.2 LOUDNESS -- the rank, curation-free (ruling 1)
# ---------------------------------------------------------------------------------------------------
#: The rule PRINTED ON THE BLOCK HEADER in words (sec 3.2). It is a literal because the header must
#: never read as a ranking of one series against another: each z is against its OWN window.
RANK_RULE_WORDS = ("ordered by how far each reading sits from its own history on its own window, then "
                   "by the graph's declared confidence")

#: The ALTERNATIVE tuple's own header words (P1, sec 3.2). A board that ranked by the banked tuple and
#: printed the shipped rule's sentence would tell the reader an ordering rule the page does not follow
#: -- the one failure mode a pre-registered alternative cannot afford, because P1 reads the ORDER off
#: the render. Two tuples, two sentences, and :func:`rank_rule_words` is the only chooser.
ALT_RANK_RULE_WORDS = ("ordered by whether each reading has crossed a level its desk convention names, "
                       "then by how far it sits from its own history on its own window")

#: THE TWO RANK RULES, by their trace words (sec 3.2, P1). `d2` is owner decision 6's shipped tuple;
#: `alternative` is the banked one. The words are the SWITCH's own vocabulary: the board carries the
#: word (``Board.rank_rule``), every consumer reads it, and no consumer carries a second bool.
RANK_RULES: tuple = ("d2", "alternative")

#: The graph's declared confidence as a number. HIGH IS LARGEST, and every consumer negates it, so a
#: hand-written `min` over the raw word can never sort the wrong way round.
CONFIDENCE_RANK: dict = {"high": 2, "medium": 1, "low": 0}


def coverage_band(row: B.NodeRow) -> int:
    """The rank tuple's LEADING term (sec 3.2), 0 (best) to 5.

        0  a served series with a z
        1  a served series with a percentile but a DECLINED z (zero variance)
        2  `series_thin` -- and a served row whose z AND percentile both declined, which is the same
           fact about the reader's position: there is a level and no standing
        3  `declared_available_unserved`
        4  `planned_text_only`
        5  `none_text_only`

    THE BAND IS NOT A FILTER. It orders; a band-5 row with dated receipts still renders, still fans and
    still enters convergence proximity. Bands 3-5 are the TEXT-ONLY tier whose own order is
    `(open_event, newest receipt date, specificity)` and is computed in STAGE 2 -- so receipt
    specificity is never a circular input to who got retrieved (sec 3.2)."""
    tier = row.coverage_tier
    if tier in ("series", "series_thin"):
        st = row.state
        if st is not None and _ok(st.z):
            return 0
        if st is not None and _ok(st.percentile):
            return 1
        return 2
    return {"declared_available_unserved": 3, "planned_text_only": 4}.get(tier, 5)


def _ok(measure) -> bool:
    """A stats.py result that MEASURED something: a dict with a value and no decline."""
    return bool(measure) and not measure.get("declined") and measure.get("value") is not None


def _abs_z(row: B.NodeRow) -> float:
    st = row.state
    return abs(float(st.z["value"])) if (st is not None and _ok(st.z)) else 0.0


def _pct_extremity(row: B.NodeRow) -> float:
    st = row.state
    return abs(float(st.percentile["value"]) - 50.0) if (st is not None and _ok(st.percentile)) else 0.0


def _run_length(row: B.NodeRow) -> int:
    st = row.state
    r = st.run if st is not None else None
    if not r or r.get("declined"):
        return 0
    return int(r.get("length") or 0)


def _convention_hit(row: B.NodeRow) -> int:
    """1 iff a DECLARED desk band is met. A TIE-BREAK, never the lead (Judges 2 and 3; ruling 1)."""
    st = row.state
    c = st.convention if st is not None else None
    return 1 if (c and not c.get("declined") and c.get("matched")) else 0


def _receipt_specificity(row: B.NodeRow) -> float:
    top = (row.receipts or {}).get("top") or []
    return float(top[0].get("rank") or 0.0) if top else 0.0


def rank_key(row: B.NodeRow) -> tuple:
    """THE D2 TUPLE (sec 3.2, owner decision 6), lexicographic, no weights, no normalising constants.

        (coverage_band, -abs_z, -pct_extremity, -run_length, -convention_hit, -receipt_specificity, id)

    THE CONSEQUENCE, STATED PLAINLY: among rows with a z, the order IS `|z|`; percentile and run break
    exact ties only; the convention is a tie-break BEHIND all three. Drafts A and D wanted `1.0/40/3`
    and `2/25/4` weightings, which is curation in disguise -- a weight is a threshold with a smooth
    edge. The writer sees all three figures on every row and judges black swan against convexity
    itself, which is the owner's ruling 1 and the boundary of sec 0.6."""
    return (coverage_band(row), -_abs_z(row), -_pct_extremity(row), -float(_run_length(row)),
            -float(_convention_hit(row)), -_receipt_specificity(row), row.driver_id)


def alt_rank_key(row: B.NodeRow) -> tuple:
    """P1'S PRE-REGISTERED ALTERNATIVE (sec 3.2, desk_cost F5/F12): `-convention_hit` AHEAD of `-abs_z`.

    BANKED, NOT SHIPPED. Defect (2)'s ORDER -- whether the TL;DR leads with the Pacific -- hangs on
    ONI's |z| position, and its +0.98 degC against its own 120-month history is a modest sigma that a
    same-month weather z (itself a z against a 45-year baseline) can out-rank. S4 banks the census under
    BOTH tuples and prints every convention-crossed row's position under each; the owner picks. NEITHER
    TUPLE EXCLUDES -- inclusion is the UNION rule of :func:`loud_set` in both."""
    return (coverage_band(row), -float(_convention_hit(row)), -_abs_z(row), -_pct_extremity(row),
            -float(_run_length(row)), -_receipt_specificity(row), row.driver_id)


def rank_rule_of(alternative) -> str:
    """The RANK RULE WORD for a caller's switch -- ``alternative_rank=True`` -> ``"alternative"``.

    It takes the bool OR the word, so the one switch survives being threaded through a kwarg, stamped
    on the board and read back off it without a second spelling appearing anywhere."""
    if isinstance(alternative, str):
        return alternative if alternative in RANK_RULES else "d2"
    return "alternative" if alternative else "d2"


def rank_key_for(alternative):
    """THE ONE SWITCH (S3 re-fix of the S2 landing). The rank tuple a caller ranks by, chosen ONCE.

    THE DEFECT THIS CLOSES, MEASURED at the S3 re-fix. ``walk(alternative_rank=True)`` threaded the flag
    to ``_stage1`` and ``_stage1`` handed it to ONE call -- ``loud_set`` -- so the alternative decided
    membership of the loud set and NOTHING else: ``row.rank`` was stamped with :func:`rank_key` whatever
    the flag said, ``board_order`` re-sorted every row by that stamp, stage 2 re-took the loud set from
    the same stamp, and the block header printed the SHIPPED rule's sentence. The board therefore
    ordered by the D2 tuple under the alternative's name -- the exact measurement error
    :func:`alt_rank_key` was banked to avoid, in the one arm that exists to measure it. P1 decides
    between the two tuples on the census at S4; a half-applied tuple would have handed that decision a
    board neither tuple ranked.

    ONE FUNCTION, EVERY CONSULTATION: the stage-1 stamp, the rank cut inside :func:`loud_set`, the
    band-crossers' and open events' order inside it, :func:`board_order`'s stage-1 AND stage-2 writes,
    Amendment 1's anchor ranking, and the header words. Everything downstream reads
    :func:`stored_rank`, which reads the stamp this function chose."""
    return alt_rank_key if rank_rule_of(alternative) == "alternative" else rank_key


def rank_rule_words(alternative) -> str:
    """The header sentence for the tuple that RAN (sec 3.2). ``render.sb_header`` reads the board's own
    ``rank_rule``, so the sentence and the ordering can never disagree."""
    return ALT_RANK_RULE_WORDS if rank_rule_of(alternative) == "alternative" else RANK_RULE_WORDS


def text_tier_key(row: B.NodeRow) -> tuple:
    """The TEXT-ONLY tier's own order (bands 3-5): `(open_event, newest receipt date, specificity)`,
    computed in STAGE 2 after ``ground()`` so specificity is never circular (sec 3.2, doctrine M-3)."""
    newest = (row.receipts or {}).get("newest_date") or ""
    return (0 if row.event_open else 1, _desc(newest), -_receipt_specificity(row), row.driver_id)


def _desc(s: str) -> tuple:
    """Descending order for a string in an ascending sort -- newest ISO date first, blanks last."""
    return (0 if s else 1, tuple(-ord(c) for c in s))


def stored_rank(row: B.NodeRow, *, alternative=False) -> tuple:
    """The row's OWN stamped tuple where stage 1 wrote one, else the tuple computed now.

    THIS IS THE LINE THAT MAKES THE ORDERING ONE ORDERING, and it closes a second one MEASURED at the
    S2 review. ``rank_key``'s sixth term is ``-receipt_specificity``, which is 0 for EVERY row in stage
    1 -- receipts do not exist before ``ground()`` -- and non-zero in stage 2. So a stage-2 caller that
    RECOMPUTED the tuple (``_stage2``'s own ``loud_set`` did) sorted by a term the stored ``row.rank``
    does not carry: two orders agreeing on the first five terms and disagreeing on ties, in a sitting
    whose law is that stage 2 appends and never re-ranks.

    The TEXT-ONLY tier is the one thing stage 2 is licensed to reorder -- sec 3.2 says its order
    ``(open_event, newest receipt date, specificity)`` "is computed in STAGE 2" -- and it has its own
    key (:func:`text_tier_key`), so this function is never asked about it.

    ``alternative`` is the FALLBACK's rule, never an override: a stamped row keeps the tuple stage 1
    wrote, and the flag only decides which tuple an UNSTAMPED row computes now. The S2 landing read the
    stamp for the shipped tuple and recomputed a fresh one for the alternative, which is what let the
    two arms rank by different stamps in stage 2; with the stamp itself chosen by
    :func:`rank_key_for`, one read serves both arms and the ordering stays ONE ordering."""
    return row.rank or rank_key_for(alternative)(row)


def rank_rows(rows, *, alternative=False) -> list:
    """Every row in rank order, the text-only tier ordered by its OWN rule inside its bands.

    THE NUMERIC HEAD READS THE STAMPED TUPLE (:func:`stored_rank`), whichever tuple stage 1 stamped, so
    stage 2 cannot move it. ``alternative`` reaches only the unstamped fallback -- a caller ranking raw
    rows (a deck, the census) gets the tuple it asked for, and a walked board gets the tuple it ran."""
    def key(r):
        return stored_rank(r, alternative=alternative)
    numeric = [r for r in rows if coverage_band(r) <= 2]
    textual = [r for r in rows if coverage_band(r) >= 3]
    return sorted(numeric, key=key) + sorted(textual, key=text_tier_key)


def board_order(bd: B.Board) -> tuple:
    """Write ``board.order`` -- sec 3.9 item 1's "ordered node list", the ONE payload key S6 threads
    into ``_select_nodes`` (cascade.py:306).

    IT IS WRITTEN TWICE PER WALK AND THAT IS NOT A RE-RANK: at the end of stage 1 (so a stage-1-only
    walk hands S6 an order at all) and at the end of stage 2, where the TEXT-ONLY tail resolves against
    receipts that did not exist before ``ground()``. The NUMERIC head is identical between the two by
    construction, because :func:`stored_rank` reads the tuple stage 1 stamped -- bar B17's own claim,
    and the deck pins it.

    THE BOARD CARRIES THE RULE (``bd.rank_rule``), so this function needs no argument and cannot be
    called with the wrong one: an alternative-tuple walk writes an alternative-tuple order on both
    passes, which the S2 landing did not do."""
    return bd.set_order(rank_rows(bd.rows, alternative=bd.rank_rule))


def loud_set(rows, *, loud_k: int, alternative=False) -> list:
    """THE LOUD SET (sec 3.2): the RANK CUT sized by mode, UNION every row past a declared desk band,
    UNION every open EVENT row. Per ANCHOR BOARD -- the cut is a board's own, never the estate's.

    THE TWO UNIONS ARE INCLUSIONS AND NEVER EXCLUSIONS, and each has a measured reason:
      * a CROSSED BAND is an ordering fact the owner licensed (ruling 1), so a row past one joins the
        set even when its |z| sits below the cut -- ONI past +0.5 degC on a Scan board is the case;
      * an OPEN EVENT row enters BY CONSTRUCTION (doctrine M-3), because without it
        `biodiesel_mandate` on palm -- coverage band 4, `planned` -- could reach Cascade's top-24 only
        through the alphabetical `driver_id` tail and would never reach Scan or Analysis at all.

    Every row BELOW the cut is still on the board. One SB-X line per mode names the rows past the cut
    whose far STATES were not read; the fan INDEX itself is free and is never cut (sec 3.6).

    ``alternative`` picks the tuple the CUT is taken under (:func:`rank_key_for`). The two unions do not
    move with it -- a band-crosser and an open event join under BOTH tuples, which is what "neither
    tuple excludes" means -- but their POSITION does, because ``out`` is emitted in rank order."""
    by_board: dict = {}
    for r in rows:
        by_board.setdefault(r.contract, []).append(r)
    out, seen = [], set()
    for _, group in sorted(by_board.items()):
        ordered = rank_rows(group, alternative=alternative)
        cut = ordered[:max(0, int(loud_k))]
        for r in ordered:
            if r in cut or r.band_crossed or r.event_open:
                if r.key not in seen:
                    seen.add(r.key)
                    out.append(r)
    return out


# ---------------------------------------------------------------------------------------------------
# 3.1 THE ANCHOR -- what the query decides, and nothing more
# ---------------------------------------------------------------------------------------------------
def resolve_anchors(*, contracts=(), named=(), attached_event: Optional[str] = None,
                    focus_driver: str = "", graph=None, max_contracts: int = 2,
                    positioning_ids=(), cold_start: bool = False, cold_start_priced=None,
                    cold_start_knobs: Optional[B.BoardKnobs] = None, key_fn=None) -> tuple:
    """The ANCHOR SET and every anchor's `source` (sec 3.1 + sec 16 Amendments 1 and 2).

    THE PRECEDENCE, and each step is a decision the design records:

      1. **AN ATTACHED EVENT OUTRANKS THE BOARD.** `_resolve_attachments` (orchestrator.py:1060; the
         LAST `route_fn` binding, :2765-2771) is an explicit gesture, and an explicit gesture wins.
      2. **A `focus_driver` ANCHORS A DRIVER** (Amendment 1): the anchor set is EVERY contract carrying
         that id, and the two-contract planner ceiling does not apply, because those contracts are not
         PLANNED -- they are read off the graph. The set arrives here in the graph's declared order
         (confidence, then the driver's own lag band, then slug) and is RE-RANKED by that driver's own
         STATE after wave 1, which is the ranking Amendment 1 asks for and which cannot exist before a
         read. `subject` rides every one of them: positioning's `context_only` rule (2.4 / D18) YIELDS
         when the query names the thing being explained.
      3. **NAMED MARKETS ARE ALL ANCHORS** (Amendment 2). `MAX_CONTRACTS` (dispatch.py:47) exists to
         bound the PLANNER's own enumeration against the composition ceiling; under the board it keeps
         that job for INFERRED seeds and stops truncating what the user NAMED. A question naming wheat,
         corn, soybeans and palm anchors all four on every tier; the cost is bounded by the read budget
         priced before the fetch (3.8), never by dropping a named market.
      4. **INFERRED SEEDS** keep the ceiling.
      5. **COLD START** (`board_loudest`, D26 / Amendment 1). V1 keeps `answer()`'s empty-route return,
         so a zero-anchor turn never reaches the board and the seam stamps `anchor_none`; this function
         therefore returns an EMPTY set unless `cold_start=True` is threaded, and :func:`cold_start_keys`
         is where the read set is PRICED. Building it here and leaving it off is what makes the
         deferral a decision rather than a gap.

         **THE ANCHORS ARE THE BOARDS THE PRICED KEYS SIT ON, AND THAT IS NOW TRUE IN CODE.** At the S2
         landing this branch enumerated every board carrying any cold-start REF and the pricer was
         called by nothing -- MEASURED as 36 anchors, 1,270 rows, 927 declared wave-1 keys and 24 read,
         of which 8 of 23 were in the priced set and the rest were `arabica_coffee`'s whole DAG,
         because the alphabetically-first board won the `anchor_order` term. `board_loudest` read the
         alphabetically FIRST board, not the estate's loudest. The pricer now runs first, the boards
         are ordered by how much of the admitted read set each carries, and :func:`walk` threads the
         admitted order into wave 1 so the cap admits the priced set and NAMES the rest.

    Duplicates collapse to their STRONGEST source, in this order -- a market that is both named and
    inferred is a NAMED anchor and is never truncated."""
    picked: dict = {}

    def _add(slug, source, *, rank=0, driver_id="", subject=False, note=""):
        slug = str(slug or "").strip()
        if not slug:
            return
        prior = picked.get(slug)
        # `named` IS MONOTONIC ACROSS THE COLLAPSE, and that is the whole reason it is a field rather
        # than a source word: the precedence ranks `focus_driver` above `named`, so a market the user
        # TYPED which also carries the attached driver would otherwise keep no record of having been
        # typed -- and the anchor ceiling would cut it in favour of the driver's own tail.
        was_named = bool(prior is not None and prior.named) or source == "named"
        if prior is not None and B.ANCHOR_SOURCES.index(prior.source) <= B.ANCHOR_SOURCES.index(source):
            if was_named and not prior.named:
                picked[slug] = replace(prior, named=True)
            return
        picked[slug] = B.Anchor(contract=slug, source=source, rank=rank, driver_id=driver_id,
                                subject=subject, named=was_named, note=note)

    if attached_event:
        _add(attached_event, "attached_event", note="attached to the question")

    if focus_driver and graph is not None:
        subject = str(focus_driver) in set(positioning_ids or ())
        for i, (slug, _terms) in enumerate(_driver_anchor_order(graph, focus_driver)):
            _add(slug, "focus_driver", rank=i, driver_id=str(focus_driver), subject=subject,
                 note="carries the driver the question names")

    for i, slug in enumerate(named or ()):
        _add(slug, "named", rank=i, note="named in the question")

    inferred = [c for c in (contracts or ()) if str(c).strip() not in picked]
    for i, slug in enumerate(inferred[:max(0, int(max_contracts))]):
        _add(slug, "planner_inferred", rank=i)

    if not picked and cold_start:
        # `board_loudest` -- the read set is priced by `cold_start_keys` FIRST, and the anchors are the
        # boards those ADMITTED keys sit on, ordered by how many of them each board carries. Nothing is
        # enumerated here that the pricer did not admit, and the assertion is checkable: every slug
        # below appears in `priced['boards']`, which is derived from `priced['keys']` alone.
        priced = cold_start_priced
        if priced is None:
            kn = cold_start_knobs or B.board_knobs_of("quick") or B.BoardKnobs(8, 4, 0, 0, 4, 24, 0, 0, 2)
            priced = cold_start_keys(kn, graph=graph, key_fn=key_fn or _default_key_fn)
        for i, slug in enumerate(priced.get("boards") or ()):
            _add(slug, "board_loudest", rank=i, note="no market was named")

    order = {s: i for i, s in enumerate(B.ANCHOR_SOURCES)}
    return tuple(sorted(picked.values(), key=lambda a: (order[a.source], a.rank, a.contract)))


def _driver_anchor_order(graph, driver_id: str) -> list:
    """Every contract carrying ``driver_id``, in the GRAPH's declared order: `(-confidence, the
    driver's own lag_min_q, slug)`. Deterministic, zero reads, and replaced by the driver's own STATE
    order after wave 1 (:func:`rank_driver_anchors`)."""
    out = []
    for slug in sorted(getattr(graph, "contracts", {})):
        d = _driver_of(graph, slug, driver_id)
        if d is None:
            continue
        band = parse_lag(getattr(d, "lag", ""))
        out.append((slug, (-CONFIDENCE_RANK.get(getattr(d, "confidence", "medium"), 1),
                           999 if band.min_q is None else band.min_q, slug)))
    out.sort(key=lambda t: t[1])
    return out


def _driver_of(graph, contract: str, driver_id: str):
    try:
        return graph.driver(contract, driver_id)
    except Exception:                                   # noqa: BLE001 -- an unknown pair is not an error
        return None


def rank_driver_anchors(bd: B.Board) -> None:
    """AMENDMENT 1's ranking, applied AFTER wave 1: a `focus_driver` anchor set is ordered by THAT
    DRIVER'S OWN STATE on each contract (the 3.2 tuple over the driver's row on that board).

    IT RUNS IN STAGE 1 AND NOT AT ANCHOR TIME because the state does not exist at anchor time, and a
    ranking asserted before its input is a ranking of the alphabet. Anchors from every other source
    keep their arrival order -- that order is the planner's, and the board does not re-plan."""
    did = bd.subject_driver
    if not did:
        return
    pos = {}
    for a in bd.anchors:
        if a.source != "focus_driver":
            continue
        r = bd.row(a.contract, did)
        # THE BOARD'S OWN TUPLE, not the shipped one by name: this ranking is "that driver's own state"
        # (Amendment 1), and under the alternative arm the driver's state is read by the alternative
        # tuple like every other rank consultation. The absent-row sentinel outranks nothing under
        # either tuple -- band 9 is past every coverage band there is.
        key = rank_key_for(bd.rank_rule)
        pos[a.contract] = key(r) if r is not None else (9, 0.0, 0.0, 0.0, 0.0, 0.0, did)
    if not pos:
        return
    # THE PRIOR (graph-declared) ORDER IS THE TIE-BREAK, and it is load-bearing rather than tidy: a
    # GLOBALLY-KEYED driver (`oni_climate`) is ONE StateRow shared by every board carrying it, so every
    # anchor's state is IDENTICAL by construction and the state rank cannot separate them. Without this
    # term the set would fall back to alphabetical order and DISCARD the confidence-and-lag order
    # `_driver_anchor_order` computed off the graph.
    prior = {a.contract: a.rank for a in bd.anchors if a.source == "focus_driver"}
    ordered = sorted(pos, key=lambda c: (pos[c], prior.get(c, 0), c))
    seat = {c: i for i, c in enumerate(ordered)}
    src = {s: i for i, s in enumerate(B.ANCHOR_SOURCES)}
    # `replace`, NEVER A RE-CONSTRUCTION: a field-by-field rebuild silently DROPS any field added
    # after it was written, which is exactly what happened to `Anchor.named` -- the re-rank threw away
    # the record that the user had typed this market, so the anchor ceiling then cut it. One ranking
    # moves one field.
    new = [a if a.source != "focus_driver" else replace(a, rank=seat[a.contract])
           for a in bd.anchors]
    bd.anchors = tuple(sorted(new, key=lambda a: (src[a.source], a.rank, a.contract)))


# ---------------------------------------------------------------------------------------------------
# 3.1 COLD START -- `board_loudest`, PRICED here so the deferral is a decision (D26)
# ---------------------------------------------------------------------------------------------------
#: The estate's SCOPE-KEYED keys by fan-out weight -- the number of node rows sharing the key across
#: boards -- measured from the configs in the design's own run (sec 3.1) and ordered as it orders them.
#: The GLOBAL-keyed refs come FIRST and cost two reads for 89 rows on 51 boards (`oni_climate` 65/33 and
#: `iod_climate` 24/18, with `oni_lag_climate` folding onto ONI through `same_series_as`).
COLD_START_GLOBAL_REFS: tuple[str, ...] = ("oni_climate", "iod_climate")
COLD_START_SCOPED_REFS: tuple[tuple[str, int, int], ...] = (
    ("fred_fx_macro", 107, 36),               # one key per currency
    ("export", 95, 31),
    ("import", 69, 34),
    ("drought_z", 67, 36),
    ("heat_stress_z", 56, 36),
    ("psd_ending_stock_su_ratio", 32, 32),
    ("brent_crude_z", 27, 27),                # a FIXED key: one read serves every board
)


def cold_start_keys(knobs: B.BoardKnobs, *, graph=None, key_fn=None, scoped=None) -> dict:
    """THE COLD-START READ SET, PRICED IN **SERIES KEYS** (sec 3.1, D26). Returns
    ``{'keys', 'global', 'scoped', 'n', 'cap', 'named', 'estate_keys', 'boards', 'by_label'}``.

    Revision 2's "the board's loudest rows across ALL contracts anchor" priced no read set at all, which
    is why it was refused. This is the price: the GLOBAL-keyed refs' keys first (2 reads serving 89 rows
    on 51 boards), then the top SCOPE-KEYED KEYS by fan-out weight -- the number of node rows sharing
    THAT KEY across boards -- cut at the mode's WAVE-1 cap (24 / 32 / 40) with its own SB-X line, never
    the whole estate (390 config-derived keys, median 14 per board).

    **KEYS, NOT REFS, AND THE DIFFERENCE IS THE WHOLE MECHANISM.** The first build priced the seven-row
    REF table above and returned n = 9 against caps of 24 / 32 / 40 -- so the cut never bound, `named`
    was ALWAYS empty, and the SB-X line sec 3.1 specifies ("no market was named; {n} of the estate's {m}
    series keys were read") could not say a number about anything. Sec 3.1 says the unit out loud --
    "the top-k SCOPE-keyed KEYS by fan-out weight ... `fred_fx_macro` 107 instances / 36 boards (ONE KEY
    PER CURRENCY)" -- and one key per currency is not one key: the ref's 107 instances are a dozen-odd
    keys of ~9 rows each, while `brent_crude_z` is a FIXED key whose 27 instances are ONE key serving 27
    rows. Ranking refs and ranking keys therefore admit different sets, and only the second is the set
    the wave-1 cap is denominated in. `key_fn` resolves each instance exactly as wave 1 will (zero
    reads: `feeders.series_key_for` is a registry walk), so the priced set and the read set are the same
    objects.

    IT IS OFF IN V1 and that is D26: `answer()` returns "No tracked contract matched this question."
    before `_answer_l2` on an empty route, so a zero-anchor turn never reaches the board; the seam
    stamps `anchor_none` and NOTHING IS READ. `named` is what the SB-X line says was left unread and
    `estate_keys` is the {m} it is measured against."""
    cap = max(0, int(knobs.wave1))
    scoped = tuple(scoped or COLD_START_SCOPED_REFS)
    prior = {r: i for i, r in enumerate(COLD_START_GLOBAL_REFS)}
    prior.update({r: len(COLD_START_GLOBAL_REFS) + i for i, (r, _n, _b) in enumerate(scoped)})
    key_fn = key_fn or _default_key_fn

    by_label: dict = {}
    estate: set = set()
    contracts = getattr(graph, "contracts", {}) or {}
    for slug in sorted(contracts):
        for d in (getattr(contracts[slug], "drivers", ()) or ()):
            ref = str(getattr(d, "silver_ref", "") or "")
            if not ref:
                continue
            plan = key_fn(ref, _WalkNode(slug, d), turn_kind="")
            if plan.key is None:
                continue
            label = plan.key.label()
            estate.add(label)                     # the {m} of the SB-X line: the estate's own key count
            if ref not in prior:
                continue
            e = by_label.setdefault(label, {"ref": ref, "rows": [], "boards": set()})
            e["rows"].append((slug, d.id))
            e["boards"].add(slug)

    def _order(item):
        label, e = item
        return (0 if e["ref"] in COLD_START_GLOBAL_REFS else 1,   # the global keys buy the most rows
                -len(e["rows"]), -len(e["boards"]), prior.get(e["ref"], 99), label)

    ranked = [lbl for lbl, _e in sorted(by_label.items(), key=_order)]
    take, left = ranked[:cap], ranked[cap:]
    boards: dict = {}
    for lbl in take:
        for slug in by_label[lbl]["boards"]:
            boards[slug] = boards.get(slug, 0) + 1
    return {"keys": take,
            "global": [x for x in take if by_label[x]["ref"] in COLD_START_GLOBAL_REFS],
            "scoped": [x for x in take if by_label[x]["ref"] not in COLD_START_GLOBAL_REFS],
            "n": len(take), "cap": cap, "named": left, "estate_keys": len(estate),
            "boards": tuple(sorted(boards, key=lambda s: (-boards[s], s))),
            "by_label": {x: {"ref": e["ref"], "rows": tuple(e["rows"]),
                             "boards": tuple(sorted(e["boards"]))} for x, e in by_label.items()}}


# ---------------------------------------------------------------------------------------------------
# 3.6 THE SHARED-DRIVER FAN-OUT -- the INDEX is free and is never cut
# ---------------------------------------------------------------------------------------------------
def fan_index(graph) -> dict:
    """``driver_id -> ((contract, sign, lag, confidence, silver_ref), ...)`` over EVERY loaded DAG.

    A LOAD-TIME INDEX OVER `display.all_driver_ids()`-shaped data, costing ZERO reads (sec 3.6). It is
    rebuilt per walk rather than cached, and that is measured rather than lazy: it is a dict build over
    1,266 already-loaded driver objects, on the order of microseconds, and a cache keyed on a graph
    OBJECT would have to answer what happens when the graph reloads. It is what makes the doctrine's
    promise structural rather than aspirational: 173 ids sit on two or more
    DAGs, and EVERY row with a shared id -- loud or not -- has its far boards NAMED with the far edge's
    own sign word. Only scope-keyed far STATE READS are priced. So a shared driver at rank 9 on Scan
    with a real anomaly is never silently unwalked."""
    out: dict = {}
    for slug, contract in sorted(getattr(graph, "contracts", {}).items()):
        for d in getattr(contract, "drivers", ()) or ():
            out.setdefault(d.id, []).append(
                (slug, getattr(d, "sign", "") or "", getattr(d, "lag", "") or "",
                 getattr(d, "confidence", "medium") or "medium",
                 str(getattr(d, "silver_ref", "") or "")))
    return {k: tuple(v) for k, v in out.items()}


def far_rows(index: dict, contract: str, driver_id: str) -> list:
    """Every FAR board of one shared id, with that board's OWN edge -- sign, band, confidence, ref.

    THE SIGN IS READ OFF THE FAR EDGE and printed as a WORD from the closed three-entry map, never
    reconciled (ruling 3): "the soybean graph declares this moves the bean price in the opposite
    direction with a lag of one to two quarters; the palm graph declares the same state moves palm in
    the same direction with a lag of two to four quarters". RENDERING THE SPLIT IS THE VALUE.

    `sign_not_unanimous` (cascade.py:7534) is a DIFFERENT fact -- several inter-commodity rows naming
    ONE child that disagree with each other -- and is never applied to a shared id (sec 1.5).

    ``edge_decline`` IS A SECOND FIELD BESIDE ``decline`` AND NOT THE SAME ONE. ``decline`` carries this
    row's FAN word (`fan_cap`, `board_unlabeled`, `child_uncovered`); the far EDGE's own absences are
    sec 6.7's `edge:` words, and folding them into one field would make a far board that was named but
    unread indistinguishable from one whose graph declared no sign. At the S2 landing a far row set
    ``sign_declared=False`` and stamped NOTHING -- the only site that stamped `sign_undeclared` was
    :func:`_edge_row`, i.e. the inter-commodity edge, so the `edge:` enum's first word was unreachable
    from the half of the walk that produces the most rows."""
    out = []
    for slug, sign, lag, conf, ref in index.get(driver_id, ()):
        if slug == contract:
            continue
        band = parse_lag(lag)
        out.append({"contract": slug, "driver_id": driver_id, "sign": sign,
                    "sign_words": SIGN_WORDS.get(sign) if sign else None,
                    "sign_declared": bool(sign), "lag": lag, "lag_band": band,
                    "confidence": conf, "ref": ref, "state_read": False, "series_key": "",
                    "free": False, "decline": None,
                    "edge_decline": ("sign_undeclared" if not sign else
                                     ("lag_unparsed" if band.unparsed else None))})
    out.sort(key=_far_order)
    return out


def _far_order(f: dict) -> tuple:
    """`(far confidence rank, far lag_min_q, board slug)` -- GRAPH-DECLARED, never the query (sec 3.6)."""
    band = f["lag_band"]
    return (-CONFIDENCE_RANK.get(f["confidence"], 1),
            999 if band.min_q is None else band.min_q, f["contract"])


# ---------------------------------------------------------------------------------------------------
# 3.4 UPSTREAM AND DOWNSTREAM -- the FULL closure on every tier; only the RENDER is capped (D27)
# ---------------------------------------------------------------------------------------------------
def path_rank(hops, rows_by_id: dict) -> tuple:
    """`(-min(confidence over hops), ancestor lag_min_q, -abs_z(ancestor), depth, driver_id)` (sec 3.4).

    THE WEAKEST HOP BOUNDS THE PATH -- `min` over the hops, so one low-confidence link cannot be hidden
    behind two high ones. The ANCESTOR'S OWN declared horizon onto the ANCHOR PRICE comes next, and it
    is never a sum along the hops: a driver's `lag` is its own lag onto the contract's target metric
    (causal/schema.py:9-11), so adding two bands would invent a horizon the graph never declared
    (doctrine M-4). Then the loudest cause first."""
    anc = hops[0]
    confs = [CONFIDENCE_RANK.get(getattr(rows_by_id.get(h), "confidence", "medium"), 1) for h in hops]
    row = rows_by_id.get(anc)
    band = row.lag_band if (row is not None and row.lag_band is not None) else parse_lag("")
    return (-min(confs) if confs else 0,
            999 if band.min_q is None else band.min_q,
            -_abs_z(row) if row is not None else 0.0,
            len(hops), anc)


def ancestor_paths(graph, bd: B.Board, contract: str, driver_id: str) -> list:
    """The SB-P UPSTREAM rows one LOUD driver produces, path-ranked (sec 3.4, D27). ZERO reads.

    WHAT AN SB-P ROW IS, in the design's own words: "UPSTREAM {a} -> {b} -> {c} -> {anchor}: the graph
    places {a} {n words} hops upstream of the {anchor} price and declares its OWN lag onto that price as
    {band words}". So a row is a PATH between two nodes of one DAG, named by the node at its TOP, and
    its ``depth`` is `ancestors_by_depth`'s own number -- which is what makes the design's example read
    "the graph places this TWO hops upstream of the bean price" for
    `crude_oil -> soybean_crush_margin -> board_crush`.

    A PATH IS EMITTED WHEN EITHER END IS LOUD, and that is not generosity -- it is what the design's own
    bar B8 requires. B8 fixes "a GRANDPARENT driver is LOUD and its child and grandchild are QUIET" and
    requires the row to render, while sec 3.4's other sentence ("upstream is walked") is about a loud
    NEAR-PRICE row finding its causes. Walking only one direction loses one of the two: seeding from
    ancestors alone gives a loud `crude_oil` no row at all (it has no ancestors on the soybean DAG), and
    seeding from descendants alone never answers "what caused this loud thing". So a loud row L emits
      * a -> ... -> L   for every ancestor a in the FULL closure, and
      * L -> ... -> c   for every descendant c,
    deduplicated by ``(top, bottom)``, which is the same row arrived at from either end.

    REVISION 2 CAPPED THE CLOSURE at 1 / 2 / `CW_DEEP_MAX_ORDER` 3 hops. That constant is the shipped
    graph's TERMINAL depth measured on the cascade walk's INTER-COMMODITY rev-links (cascade.py:6458) --
    a DIFFERENT graph from intra-DAG ancestry, whose own closure `ancestors_by_depth` measures at median
    2, mean 3.58, max 26 (graph.py:293). Borrowing it would have cut a fourth-hop cause on Cascade with
    a number that never measured this closure. So the closure is walked WHOLE on every tier (BFS over
    loaded YAML; the 26-ancestor monster costs microseconds), every node's state is already on the board
    because its key is an anchor-DAG key, and the MODE caps only how many SB-P rows RENDER.

    THE BAND ON THE ROW IS THE TOP NODE'S OWN, NEVER A SUM (doctrine M-4). A driver's `lag` is its own
    lag onto the contract's target metric (causal/schema.py:9-11), so `crude_oil`'s 0-2 quarters is its
    declared horizon onto the BEAN PRICE, and adding the two hops below it would invent 0-4."""
    rows_by_id = {r.driver_id: r for r in bd.rows_for(contract)}
    pairs = {}
    try:
        for a, depth in graph.ancestors_by_depth(contract, driver_id).items():
            pairs[(a, driver_id)] = int(depth)
    except Exception:                                   # noqa: BLE001
        pass
    try:
        for c, dist in graph.descendants_by_depth(contract, driver_id).items():
            pairs[(driver_id, c)] = abs(int(dist))
    except Exception:                                   # noqa: BLE001
        pass
    out = []
    for (top, bottom), depth in sorted(pairs.items()):
        hops = _hops_to(graph, contract, top, bottom)
        row = rows_by_id.get(top)
        band = row.lag_band if (row is not None and row.lag_band is not None) else parse_lag("")
        out.append({"contract": contract, "seeded_by": driver_id, "ancestor": top, "bottom": bottom,
                    "depth": int(depth), "hops": tuple(hops), "lag_band": band,
                    "band_is_the_ancestors_own": True,
                    "confidence": getattr(row, "confidence", "medium") if row is not None else "medium",
                    "rank": path_rank(hops, rows_by_id), "rendered": False, "decline": None})
    out.sort(key=lambda p: p["rank"])
    return out


def _hops_to(graph, contract: str, top: str, bottom: str) -> list:
    """The SHALLOWEST parent chain ``[top, ..., bottom]``, BFS upward from ``bottom``.

    SHALLOWEST, because that is what `ancestors_by_depth` itself keeps -- "BFS, so a cause reachable by
    two paths keeps its SHALLOWEST depth" (graph.py:293) -- and the SB-P line's claim is how many hops
    upstream the top node sits. A longer branch would OVERSTATE that distance, and the estate already
    has one convention for this question."""
    seen, frontier = {bottom: None}, [bottom]
    while frontier:
        nxt = []
        for node in frontier:
            d = _driver_of(graph, contract, node)
            for par in (getattr(d, "parents", ()) or ()):
                if par in seen:
                    continue
                seen[par] = node
                if par == top:
                    chain, cur = [], par
                    while cur is not None:
                        chain.append(cur)
                        cur = seen[cur]
                    return chain
                nxt.append(par)
        frontier = nxt
    return [top, bottom] if top != bottom else [top]


def descendant_rows(graph, contract: str, driver_id: str) -> list:
    """"What this state feeds" (sec 3.4): the descendants of a loud driver with their own state rows.
    Zero reads -- every descendant is an anchor-DAG node and its key was already priced in wave 1."""
    try:
        des = graph.descendants_by_depth(contract, driver_id)
    except Exception:                                   # noqa: BLE001
        return []
    return [{"contract": contract, "parent": driver_id, "child": cid, "distance": int(d)}
            for cid, d in sorted(des.items())]


# ---------------------------------------------------------------------------------------------------
# 3.5 INTER-COMMODITY EDGES, COMPLEXES, CHAINS, CONVERGENCE
# ---------------------------------------------------------------------------------------------------
#: Which edge directions a tier walks (sec 7's "walk depth" row). Scan takes the forward hop only;
#: Analysis takes both ways; Cascade takes both ways from every DAG a LOUD driver touches. A direction a
#: tier does not walk is stamped `path: edge_hop_cap` -- named, never silently absent.
EDGE_DIRECTIONS: dict = {"quick": ("forward",), "deep": ("forward", "reverse"),
                         "max": ("forward", "reverse")}


def cross_edges(graph, contract: str, directions=("forward", "reverse")) -> list:
    """`cross_links` (the boards that DRIVE this one) and `rev_cross_links` (the boards this one
    CASCADES INTO), each carrying `relation, sign, lag` off the declared edge (schema.py:64).

    BOTH SIDES' CONTRACT NODES GET A BOARD ROW (their top-3 loud drivers, read in wave 2 where the
    far-key cap admits them and NAMED with their signs otherwise), so the spillover paragraph has STATE
    to cite and not only an edge."""
    out = []
    if "forward" in directions:
        try:
            for e in graph.cross_links(contract):
                out.append(_edge_row(contract, e, "forward"))
        except Exception:                               # noqa: BLE001 -- cross_links may KeyError
            pass
    if "reverse" in directions:
        for e in (graph.rev_cross_links(contract) or ()):
            out.append(_edge_row(contract, e, "reverse"))
    return out


def _edge_row(contract: str, e: dict, direction: str) -> dict:
    sign = str(e.get("sign") or "")
    band = parse_lag(e.get("lag") or "")
    other = (e.get("target_contract") or e.get("driver_commodity") if direction == "forward"
             else e.get("contract"))
    return {"anchor": contract, "direction": direction, "other": other,
            "declared": e.get("driver_commodity") or e.get("seed") or "",
            "relation": e.get("relation") or "", "sign": sign,
            "sign_words": SIGN_WORDS.get(sign) if sign else None,
            "sign_declared": bool(sign), "lag": e.get("lag") or "", "lag_band": band,
            "mechanism": e.get("mechanism") or "", "tracked": bool(e.get("tracked", True)),
            "decline": (None if sign else "sign_undeclared") or (None if not band.unparsed else
                                                                 "lag_unparsed")}


#: Words a convergence row may NEVER carry (sec 3.5, doctrine M-2). The board renders PROXIMITY IN
#: WORDS; FIRING stays with `firing.fire_contract` over DECLARED bands. Revision 1 handed `graph.regimes`
#: the mode-sized rank cut, which made "met" a function of LIST LENGTH and MODE: on Cascade every mapped
#: soybean driver inside the cut of 24 was "active" regardless of any z, so `bearish_glut` (3 of 5) read
#: met on Cascade and not on Scan at ONE as-of -- the K9 class (1)/(3) shape minted by arithmetic.
CONVERGENCE_BANNED_WORDS: tuple[str, ...] = ("met", "fires", "regime is")


def convergence_rows(graph, contract: str, loud_ids, *, loud_k: int, band_ids=(),
                     measured_ids=None) -> list:
    """ONE row per DECLARED pattern on a board, as PROXIMITY, plus its amplifier sub-lines (sec 3.5, D24).

    EVERY PATTERN, NOT THE FIRED ONES. `graph.regimes` returns only patterns whose matched count clears
    `requires_any_n_of`, which is the FIRING question and belongs to `firing.fire_contract`. The board
    asks a different question -- how close is this pattern, on this board, at this as-of -- and a
    pattern at one of three is a row that SAYS one of three.

    THE 277 `Interaction` ROWS ARE THE GRAPH'S ONLY AMPLIFIER SEMANTICS (D24, 271 amplifies / 6 dampens)
    and they are not thrown away and not fired: an Interaction whose `when` ids are ALL in the loud set
    renders one digit-free sub-line under its pattern, and one whose ids are not declines
    `interaction: when_not_all_loud` on the trace and is not rendered -- the PATTERN row still is.

    `measured_ids` IS WHICH OF THE LOUD IDS CARRY A STATE THIS BOARD ACTUALLY READ, and the row keeps it
    beside `matched` rather than instead of it. The loud set admits rows with NO state by construction
    (a crossed band, an open event -- doctrine M-3), so `matched` is the true ORDERING count and the
    split is what lets sec 6.2's template keep its promise that every name it lists carries its own
    `[N]` z. `None` -- the default -- means the caller is not making the distinction, and every matched
    id is then reported as it was before."""
    loud, banded = set(loud_ids), set(band_ids)
    measured = None if measured_ids is None else set(measured_ids)
    out = []
    contract_obj = (getattr(graph, "contracts", {}) or {}).get(contract)
    for s in (getattr(contract_obj, "convergence", ()) or ()):
        matched = [d for d in s.drivers if d in loud]
        seen_state = matched if measured is None else [d for d in matched if d in measured]
        unread = [] if measured is None else [d for d in matched if d not in measured]
        inter = []
        for it in (getattr(s, "interactions", ()) or ()):
            when = list(it.when)
            all_loud = set(when) <= loud
            inter.append({"when": tuple(when), "effect": it.effect, "note": it.note,
                          "rendered": all_loud,
                          "unmeasured": (() if measured is None else
                                         tuple(d for d in when if d not in measured)),
                          "decline": None if all_loud else "when_not_all_loud"})
        out.append({"contract": contract, "name": s.name, "direction": s.direction,
                    "threshold": int(s.requires_any_n_of), "drivers": tuple(s.drivers),
                    "matched": tuple(matched), "n_matched": len(matched),
                    "matched_measured": tuple(seen_state), "matched_unmeasured": tuple(unread),
                    "n_declared": len(s.drivers), "loud_k": int(loud_k),
                    # `ConvergenceSignal.note` IS NOT COPIED HERE (S6 second verify, minor (b)). It was,
                    # and `render.sb_convergence` reads no such key -- so the row carried a second
                    # ungoverned config-prose string, from the same gitignored DAG files as
                    # `Interaction.note`, sitting one edit away from a template that would splice it
                    # into a rendered line with no fence in front of it. The interaction note earns its
                    # place on the row above because a row DOES render it, through
                    # `render.governed_note` and the assembled-row fence beside it; this one earned
                    # nothing but the risk. A future row that wants it takes it from the signal and
                    # renders it through `governed_note`, which is where the grading lives.
                    "n_with_band": sum(1 for d in matched if d in banded),
                    "interactions": tuple(inter)})
    out.sort(key=lambda r: (-r["n_matched"], r["name"]))
    return out


def complex_pairs(pairs, on_board) -> list:
    """The 35 declared pairs (`complex_map.yaml`) that render: BOTH sides on the board (sec 3.5).

    A pair is VOCABULARY, never a decision. Its RV rows (World su_ratio per side, the price standing)
    enter as EVIDENCE rows UNDER the pair and never as the thing that decided it -- RV / regional legs
    are rows, never relevance gates."""
    have = set(on_board)
    return [{"pair": tuple(p), "rendered": set(p) <= have} for p in (pairs or ())]


def chain_paths(chains, on_board, *, loud_boards=()) -> list:
    """`chain_map.yaml` (10) and `transmission_map.yaml` (2) as DECLARED PATHS, ordered by the number of
    LOUD hops then hops on the board then FILE ORDER (sec 3.5). Selection by file order ALONE retires
    in phase 4.

    ``loud_hops`` AND ``hops_on_board`` ARE TWO COUNTS AND THE FIRST BUILD HAD ONLY ONE. It called
    "hops on the board" `loud_hops`, so a chain every one of whose boards was touched and none of whose
    boards carried a loud row out-ranked a chain with one genuinely loud hop -- sec 3.5's ordering word
    measuring presence instead of loudness. ``loud_boards`` is the set of boards carrying at least one
    row in the loud set; empty (the default) means the caller is asking the presence question only, and
    every ``loud_hops`` is then 0 and the file order decides, which is the honest degenerate case."""
    have, loud = set(on_board), set(loud_boards)
    out = []
    for i, ch in enumerate(chains or ()):
        hops = tuple(ch.get("hops") or ())
        out.append({"name": ch.get("name") or f"chain_{i}", "hops": hops,
                    "loud_hops": sum(1 for h in hops if h in loud),
                    "hops_on_board": sum(1 for h in hops if h in have), "file_order": i,
                    "rendered": bool(hops) and all(h in have for h in hops)})
    out.sort(key=lambda c: (-c["loud_hops"], -c["hops_on_board"], c["file_order"]))
    return out


# ---------------------------------------------------------------------------------------------------
# 3.7 DATED EVENTS -- they stay on the board and project forward until their band expires
# ---------------------------------------------------------------------------------------------------
#: Day beats month beats year when two receipts claim the same event date (sec 3.7, critic G17).
EVENT_PRECISION_RANK: dict = {"day": 0, "month": 1, "year": 2, "": 3}


def event_date_for(receipts, asof: str) -> tuple:
    """`(event_date, precision)` for a node, or ``(None, '')`` (sec 3.7). THE RULE, not "the newest".

    `max(event_date)` over the node's receipts with `event_date <= asof`, ties broken by
    `event_date_precision` (day over month over year -- both fields ride every evidence row,
    evidence.py:427 / :601) and then by the EARLIER PUBLICATION DATE. The receipt's own `date`
    (publication) is NEVER the event date: an analysis piece published a month after the event carries
    the event's own `event_date` when the extractor stamped one and otherwise contributes no date at
    all. A receipt with `event_date > asof` never anchors -- it is a kind-5 WATCH candidate."""
    ed, prec, _rc = event_receipt_for(receipts, asof)
    return (ed, prec)


def event_receipt_for(receipts, asof: str) -> tuple:
    """`(event_date, precision, receipt)` -- :func:`event_date_for`'s rule WITH THE WINNER CARRIED OUT.

    THE RENDER NEEDS THE DOCUMENT, NOT ONLY THE DATE. SB-D prints "{event} dated {ISO} by [E{k}]
    (published {ISO})", and the first cut read both the publication date and the handle off
    `receipts['top'][0]` -- the caller's first receipt in INSERTION order, which `_receipt_summary`
    never sorts. On the harness that printed the right date only because the fixture lists the event
    document first; on the real path receipts arrive ranked by recency and specificity (sec 2.2), which
    would have put a later levy document first and rendered a false attribution under a handle pointing
    at the wrong document. One rule chooses the date, so the same rule names the document."""
    best = None
    winner = None
    for r in (receipts or ()):
        ed = str((r.get("event_date") if isinstance(r, dict) else getattr(r, "event_date", "")) or "")
        if not ed or (asof and ed[:10] > str(asof)[:10]):
            continue
        prec = str((r.get("event_date_precision") if isinstance(r, dict)
                    else getattr(r, "event_date_precision", "")) or "")
        pub = str((r.get("date") if isinstance(r, dict) else getattr(r, "date", "")) or "")
        cand = (ed, EVENT_PRECISION_RANK.get(prec, 3), pub, prec)
        if best is None or (cand[0] > best[0]) or (cand[0] == best[0] and cand[1:3] < best[1:3]):
            best, winner = cand, r
    if best is None:
        return (None, "", None)
    return (best[0], best[3],
            dict(winner) if isinstance(winner, dict) else
            {"date": str(getattr(winner, "date", "") or ""),
             "source": str(getattr(winner, "source", "") or ""),
             "text": str(getattr(winner, "text", "") or ""),
             "tier": getattr(winner, "tier", 3),
             "event_date": best[0]})


def _cut_pairs(items) -> tuple:
    """``(contract, driver_id)`` for every deferred key a cut dropped -- the NAMES the render owes.

    Sec 3.8's law is "the tail it cannot afford is NAMED", and the render cannot name a
    ``SeriesKey.label`` (a raw ref plus a scope) without tripping ``register.internal_leaks``. Wave 1
    defers :class:`PricedKey` instances, which carry the pair; wave 2 additionally defers the analog
    seats, which are ``'{column}:{contract}:{driver_id}'`` strings -- both shapes resolve here so the
    render has ONE field to read and never parses a budget token itself."""
    out = set()
    for x in items or ():
        c = str(getattr(x, "contract", "") or "")
        d = str(getattr(x, "driver_id", "") or "")
        if not c and isinstance(x, str) and x.count(":") >= 2:
            _col, c, d = x.split(":", 2)
        if c:
            out.add((c, d))
    return tuple(sorted(out))


def event_is_open(event_date: Optional[str], band: LagBand, asof: str) -> bool:
    """Is the declared lag band from this event still OPEN at the as-of (sec 3.7)?

    `structural` (max_q None) opens and does not close. A band with no max end cannot expire; a band the
    table could not parse has NO band at all, so the row cannot claim a window and the answer is False
    -- the row stays as HISTORY with its age clause, which is a sentence rather than a silence."""
    if not event_date or band.min_q is None:
        return False
    if band.max_q is None:
        return True
    return _add_months(event_date, int(band.max_q) * QUARTER_MONTHS) >= str(asof)[:10]


def _add_months(iso: str, months: int) -> str:
    """ISO date + N months, clamped to the month end. Pure calendar arithmetic, no clock."""
    y, m, d = int(iso[0:4]), int(iso[5:7]), int(iso[8:10] or 1)
    total = (y * 12 + (m - 1)) + int(months)
    y2, m2 = total // 12, total % 12 + 1
    last = [31, 29 if (y2 % 4 == 0 and (y2 % 100 != 0 or y2 % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m2 - 1]
    return f"{y2:04d}-{m2:02d}-{min(d, last):02d}"


def projection_window(anchor_date: str, band: LagBand) -> dict:
    """SB-J's two months, from the row's own printed anchor date and the edge's OWN band (sec 3.7, B10).

    PROJECTION rows anchor at the driver's STATE date -- the start of its current run, or its crossing
    of a declared band where one exists, else the level date -- and the row prints WHICH anchor it used.
    EVENT rows anchor at the EVENT date. Never a summed band, never a point."""
    if not anchor_date or band.min_q is None:
        return {"opens": None, "closes": None, "open_ended": False, "declined": "lag_unparsed"}
    opens = _add_months(anchor_date, int(band.min_q) * QUARTER_MONTHS)
    if band.max_q is None:
        return {"opens": opens, "closes": None, "open_ended": True, "declined": None}
    return {"opens": opens, "closes": _add_months(anchor_date, int(band.max_q) * QUARTER_MONTHS),
            "open_ended": False, "declined": None}


def horizon_sits(horizon_months: Optional[int], window: dict, anchor_date: str) -> Optional[str]:
    """"the horizon asked about ... sits {inside | before | past} that window" (SB-J, sec 3.1).

    BOARD MONTH-ARITHMETIC, never the writer's: the clause is computed from the same two months SB-J
    already prints, so a reader can check it against the line above it.

    ``anchor_date`` IS THE DATE THE HORIZON IS COUNTED FROM, and it is NOT necessarily the date the
    WINDOW is counted from. The window runs from the driver's own STATE date (a lag runs from the state
    to the effect, Judge 2); a question's "three months from now" runs from the AS-OF. The render
    therefore passes the as-of here while passing the state date to :func:`projection_window` -- two
    different counted-from dates on one line, which is why this argument is a parameter rather than a
    field read off the window. Passing the state date instead makes the clause vacuous on the commonest
    case: three months from a run's start is inside a one-to-two-quarter window from that same start,
    always, whatever the question asked."""
    if horizon_months is None or not anchor_date or window.get("opens") is None:
        return None
    at = _add_months(anchor_date, int(horizon_months))
    if at < window["opens"]:
        return "before"
    if window.get("closes") and at > window["closes"]:
        return "past"
    return "inside"


# ---------------------------------------------------------------------------------------------------
# 3.8 THE READ BUDGET -- two waves, each priced BEFORE its fetch, atomic
# ---------------------------------------------------------------------------------------------------
class PricedKey(NamedTuple):
    """One key the board MAY read, with everything the wave-1 rank needs and nothing it does not."""
    label: str                 # the SeriesKey label -- the unit of the read (sec 1.1)
    ref: str
    contract: str
    driver_id: str
    anchor_order: int          # 0 = the first anchor board; the design's "anchor board first"
    share: int                 # node rows sharing this key -- "one global ONI read serves 65 rows"
    confidence: int            # the graph's declared confidence as a number, HIGH largest
    free: bool = False         # the memo already holds this series: priced at ZERO


def wave1_order(k: PricedKey) -> tuple:
    """`(anchor board first; then the number of node rows sharing the key; then confidence rank; then
    ref)` -- Draft A's fan-out weighting, and the ONE place wave 1 is ordered (sec 3.8).

    THE SHARING TERM IS WHY THE ORDER IS NOT ALPHABETICAL: a key on eleven of a board's rows buys eleven
    rows for one read, and a cap that dropped it to keep a single-row key would spend the same money for
    a tenth of the board."""
    return (k.anchor_order, -k.share, -k.confidence, k.ref, k.label)


def dedup_by_label(keys) -> list:
    """Collapse priced keys onto their SERIES KEY, keeping the best-ranked instance of each.

    THE READ COUNT OF A TURN IS THE DISTINCT SERIES-KEY COUNT (sec 1.1), and this is the line that makes
    that true in code rather than in prose. Two node rows can carry ONE key -- the soybean board's
    `El_Nino` and the palm board's `oni_lag_climate` fold onto `(oni_climate, _global)` through
    `same_series_as`, and 35 boards share that one reading -- so pricing them as two would charge twice
    for a series the memo serves once and would shrink the cap by every fold the design exists to
    exploit. MEASURED at this landing: on a soybeans+palm anchor pair the un-deduplicated wave-1 plan
    declared two ONI keys, i.e. the fold cost a read instead of saving one.

    The surviving instance keeps the best `wave1_order` position, so the KEY is priced at the rank of
    the loudest board that carries it."""
    best: dict = {}
    for k in sorted(keys, key=wave1_order):
        best.setdefault(k.label, k)
    return sorted(best.values(), key=wave1_order)


def price_wave1(keys, *, cap: int) -> dict:
    """CUT BEFORE THE FETCH (sec 3.8). Returns ``{'plan', 'deferred', 'declared', 'free'}``.

    THE TRIM ORDER IN WAVE 1 is "the lowest-ranked anchor keys" and there is nothing else in the wave to
    trim. FREE KEYS (the memo already holds the series) are never counted against the cap and never
    deferred -- a key that costs nothing cannot be the reason another key was dropped.

    EVERY DROPPED KEY IS NAMED, on the `budget_cap` SB-X row and on the trace. That is the whole
    difference between this and `CASCADE_CAP` truncating a built list by walk order (cascade.py:1515):
    a budget cut here can never read as a zero."""
    ordered = dedup_by_label(keys)
    free = [k for k in ordered if k.free]
    paid = [k for k in ordered if not k.free]
    plan = paid[:max(0, int(cap))]
    deferred = paid[max(0, int(cap)):]
    return {"plan": tuple(plan), "deferred": tuple(deferred), "free": tuple(free),
            "declared": len(ordered)}


def price_wave2(*, far_keys, analog_benchmarks=(), analog_receipts=(), legb_cells=0,
                legb_on: bool = False, knobs: B.BoardKnobs) -> dict:
    """WAVE 2, PRICED AFTER THE RANK AND BEFORE ITS OWN FETCH (sec 3.8, doctrine M-1).

    WHY THIS WAVE CANNOT BE PRICED WITH WAVE 1, stated because revision 1 tried: the precedent it cited
    -- `_transmission_legs` pricing `net = 2 * len(su_keys)` before any fetch (cascade.py:5880) -- works
    only because its PAIR SET is known before the read. The board's far set is not: it depends on the
    LOUD set, which depends on the wave-1 arrays. So there are two rectangles, not one.

    THE COLUMN CAPS come from :func:`board.wave2_shape` -- all four derive from the nine knobs, so a
    knob edit can never leave the columns and the total disagreeing. Over the total, the TRIM ORDER is
    the design's: leg-B cells -> analog receipts -> the lowest-ranked far keys -> analog benchmark
    reads. Analog benchmarks trim LAST because a leg-A outcome with no benchmark is an outcome nobody
    can place."""
    shape = B.wave2_shape(knobs, legb_cells=legb_cells, legb_on=legb_on)
    far = dedup_by_label(far_keys)
    free = [k for k in far if k.free]
    paid = [k for k in far if not k.free]

    cols = {"far": list(paid[:shape["far"]]),
            "analog_benchmark": list(analog_benchmarks)[:shape["analog_benchmark"]],
            "analog_receipts": list(analog_receipts)[:shape["analog_receipts"]],
            "legb": list(range(shape["legb"]))}
    deferred = {"far": list(paid[shape["far"]:]),
                "analog_benchmark": list(analog_benchmarks)[shape["analog_benchmark"]:],
                "analog_receipts": list(analog_receipts)[shape["analog_receipts"]:],
                "legb": []}

    total = int(shape["total"])
    for col in ("legb", "analog_receipts", "far", "analog_benchmark"):
        while sum(len(v) for v in cols.values()) > total and cols[col]:
            deferred[col].insert(0, cols[col].pop())

    declared = (len(far) + len(list(analog_benchmarks)) + len(list(analog_receipts)) + shape["legb"])
    return {"plan": tuple(cols["far"]), "columns": {k: tuple(v) for k, v in cols.items()},
            "deferred": {k: tuple(v) for k, v in deferred.items()},
            "free": tuple(free), "declared": declared, "shape": shape,
            # THE FAR HALF ALONE, because it is the half THIS sitting executes. The analog columns are
            # PRICED here (the seats are reserved against the wave-2 cap, which is what stops a later
            # leg from over-spending it) and are SPENT by S3's analog leg. A rectangle that counted a
            # reserved seat as READ would report reads nobody made -- the same lie a budget cut reading
            # as a zero would tell, from the other direction.
            "far_declared": len(far), "far_deferred": tuple(deferred["far"]),
            "n_planned": sum(len(v) for v in cols.values())}


class _WidthGuard:
    """Counts CONCURRENT reads so "the pool never exceeds width 2" (B3) is measured rather than trusted.

    The board's reads are on the NUMBERS bulkhead through `pgnumbers.pg_query` under the board's OWN
    counter (2.1, D20). On a hybrid turn the numbers agent's 4-wide rounds share the 4-slot pool with
    the board's 2 -- six borrowers on four slots when they overlap -- which is why the width is a rule
    and not a suggestion, and why a slot that does not free declines `pool_exhausted` BY NAME rather
    than falling back to Athena."""

    def __init__(self):
        self.now = 0
        self.peak = 0
        self._lock = threading.Lock()

    def __enter__(self):
        with self._lock:
            self.now += 1
            self.peak = max(self.peak, self.now)
        return self

    def __exit__(self, *exc):
        with self._lock:
            self.now -= 1
        return False


def run_wave(plan, fetch, *, ledger: B.WaveLedger, width: int = 2, guard=None) -> dict:
    """Execute ONE priced wave: ``fetch(key) -> (row, reads)``. Returns ``{key.label: row}``.

    ONE ThreadPoolExecutor wave at width ``min(2, n)``; the ledger counts what came back. The wave is
    ATOMIC in the sense of sec 3.8 -- the plan was cut before this function was called, and this
    function cannot add to it."""
    out: dict = {}
    if not plan:
        return out
    guard = guard or _WidthGuard()
    t0 = time.perf_counter()

    def _one(k):
        ledger.note_fetch()
        with guard:
            return k, fetch(k)

    n = min(max(1, int(width)), len(plan))
    with ThreadPoolExecutor(max_workers=n) as ex:
        for k, (row, reads) in ex.map(_one, plan):
            out[k.label] = row
            ledger.reads_used += int(reads)
    ledger.ms = (time.perf_counter() - t0) * 1000.0
    return out


# ---------------------------------------------------------------------------------------------------
# THE WALK ITSELF -- sec 3.3's fourteen steps, in two stamped stages
# ---------------------------------------------------------------------------------------------------
class _WalkNode:
    """What ``cascade._scope_ex`` / ``_region_row`` read: `.contract`, `.id`, `.prior`, `.evidence`.
    The census's `_LegNode` stand-in, minted here from the DAG's own Driver so the board never asks the
    planner for a node it can build from the graph."""
    __slots__ = ("contract", "id", "prior", "evidence")

    def __init__(self, contract, driver):
        self.contract, self.id = contract, driver.id
        self.prior = {"silver_ref": getattr(driver, "silver_ref", None),
                      "region": getattr(driver, "region", None)}
        self.evidence = []


#: Every leg the board orchestrates (sec 6.7). The walk stamps `not_reached` for every one it did not
#: enter -- A LEG CANNOT STAMP ITS OWN ABSENCE, which is the hole the reading's 4.8 measured.
ALL_LEGS: tuple[str, ...] = ("series", "edge", "fan", "path", "interaction", "tape", "analog",
                             "watch", "render", "board")

#: The `anchor_order` seat a COLD-START key the pricer did not admit takes: past every admitted seat, so
#: `price_wave1`'s cut is exactly the priced set and every unadmitted key is DEFERRED BY NAME.
_UNADMITTED = 1 << 20


def _dominant_decline(words, *, deferred: int) -> str:
    """The `series:` word a wave that read NOTHING should carry (sec 6.7).

    `budget_cap` IS A CLAIM ABOUT A CUT, and the S3 render owes that word a sentence naming the dropped
    keys -- so it is only honest when keys were actually dropped. When `deferred == 0` the reads were
    priced, attempted and REFUSED, and the refusal already has a word of its own on every row. Ties
    break on SERIES_REASONS' own first-appearance order, which is the estate's convention for a closed
    enum and keeps the stamp deterministic across two runs of the same turn."""
    counts: dict = {}
    for w in words:
        w = B.reason_word(w)
        if w in B.SERIES_REASONS:
            counts[w] = counts.get(w, 0) + 1
    if deferred or not counts:
        return "budget_cap"
    return sorted(counts, key=lambda w: (-counts[w], B.SERIES_REASONS.index(w)))[0]


def walk(*, graph, asof: str, mode: str = "deep", anchors=(), question: str = "",
         state_fn=None, key_fn=None, receipts=None, turn_kind: str = "", lane: str = "run_hybrid",
         knobs: Optional[B.BoardKnobs] = None, width: int = 2, legb_on: bool = False,
         alternative_rank: bool = False, complexes=(), chains=(),
         positioning_ids=(), stage2: bool = True, cold_start: bool = False,
         analog_reads: bool = True) -> B.Board:
    """THE WALK, in the order of sec 3.3, and it never replans.

    ``state_fn(ref, node) -> (StateRow, reads)`` and ``key_fn(ref, node) -> KeyPlan`` are INJECTED.
    That is what makes every bar of sec 10.2 runnable on fixture arrays with no pg mirror, and it is
    also the honest shape: the board's executor is a bulkhead the walk is handed, never one it opens.

    ``receipts`` is ``{(contract, driver_id): [receipt dicts]}`` -- STAGE 2's input, and it does not
    exist before `ground()` fills `n.evidence`, which is exactly why there are two stages.

    THE STAGES ARE STAMPED (D11): stage 1 (numeric state, the rank, wave 1) runs AFTER
    `pl.grounded_subgraph` and BEFORE `pl.ground`; stage 2 (receipts, EVENT rows, the text-tier rank,
    wave 2) runs AFTER `ground` and BEFORE `cq.quantify`. Stage 2 NEVER re-orders stage 1's rows; it
    appends -- and :func:`walk` asserts that by ranking once, in stage 1, and never again.

    ``alternative_rank`` IS ONE SWITCH AND IT MOVES EVERYTHING THE RANK DECIDES (sec 3.2, P1). It is
    STAMPED on the board as ``rank_rule`` before either stage runs, and from there it reaches the
    stage-1 stamp, the loud cut, both ``board_order`` writes, Amendment 1's anchor ranking, the trace
    and the block header's own sentence. The S2 landing threaded it to ONE call and the arm ranked by
    the shipped tuple under the alternative's name; :func:`rank_key_for` is where that is closed."""
    # NO KNOBS, NO BOARD -- `board_knobs_of`'s own docstring word, honoured rather than defaulted around.
    # THE FALLBACK THIS REPLACES WAS `... or B.BoardKnobs(8, 4, 0, 0, 4, 24, 0, 0, 2)`, i.e. a preset the
    # tier table declares NO board for (`deep_v2`, `max_cc1`, `quick_r0`, `quick_s` all return None from
    # `board_preset`) ran silently at SCAN depth. On an arm running a dark twin that is a parity error
    # nothing stamps: the control and the treatment would differ by a board neither declared. A tier with
    # no declared board is an OFF LANE and says so with its own name in the detail (sec 6.7's
    # `lane_off:<...>`), which is a sentence the S3 render already owes that word.
    kn = knobs or B.board_knobs_of(mode)
    bd = B.Board(asof=str(asof or "")[:10], mode=mode, knobs=kn, anchors=tuple(anchors),
                 graph_version=getattr(graph, "version", None), turn_kind=turn_kind,
                 horizon_months=parse_horizon(question),
                 rank_rule=rank_rule_of(alternative_rank))
    if kn is None:
        bd.stamp_not_reached(*ALL_LEGS)
        bd.stamp("board", "declined", reason=f"lane_off:{mode}")
        return bd
    legb_cells = B.legb_cells_of(mode)
    bd.stamp_not_reached(*ALL_LEGS)

    # ── the LANE gate (sec 7). An off lane stamps its word so `BoardFired` is absent-when-inapplicable.
    if lane in B.OFF_LANES:
        bd.stamp("board", "declined", reason=f"lane_off:{lane}")
        return bd
    # ── COLD START (D26). V1 keeps `answer()`'s empty-route return, so the board never runs anchorless;
    #    `cold_start=True` is the V1.1 arm, and when it is threaded the READ SET IS PRICED FIRST and the
    #    anchors are the boards those admitted keys sit on. `admit_order` carries the pricer's own
    #    positions into wave 1's `anchor_order` term, which is what makes the plan the priced set rather
    #    than the alphabetically-first board's DAG. Everything else is still DECLARED and NAMED on the
    #    `budget_cap` note, so a cold start starves nothing silently.
    admit_order = None
    if not bd.anchors and cold_start:
        priced = cold_start_keys(kn, graph=graph, key_fn=key_fn or _default_key_fn)
        bd.anchors = resolve_anchors(graph=graph, cold_start=True, cold_start_priced=priced)
        admit_order = {lbl: i for i, lbl in enumerate(priced["keys"])}
        # SB-X, sec 3.1's own line: "no market was named; {n} of the estate's {m} series keys were read
        # for the loudest drivers". The note is the producer that line reads; at the S2 landing there
        # was none, so the sentence had no numbers to print.
        bd.notes.append({"kind": "cold_start", "read": priced["n"], "cap": priced["cap"],
                         "estate_keys": priced["estate_keys"],
                         "boards": len(priced["boards"]), "unread": len(priced["named"]),
                         "names": tuple(priced["named"])})
    if not bd.anchors:
        bd.stamp("board", "declined", reason="anchor_none")
        return bd

    # ── THE ANCHOR CEILING (S6 review). `resolve_anchors` bounds only INFERRED seeds: Amendment 1's
    #    driver anchor set is EVERY contract carrying the id, by design, and Amendment 2's named set is
    #    exempt from `max_contracts` by design. MEASURED on the shipped graph: `El_Nino` and
    #    `heat_stress` are each carried by 35 contracts and `crude_oil` by 24, so ONE FE gesture
    #    (`_resolve_attachments` -> `focus_driver`) put 35 DAGs on the board -- declared cap 106 against
    #    the design's 71, 916 rendered rows, ~37,450 writer tokens, and 35 SERIAL tape reads. Every
    #    render cap this design ships is per ROW CLASS and none of them can see the anchor count, so
    #    the bound has to live here, where the tier's own knob is in hand.
    #
    #    IT IS A CUT THAT NAMES WHAT IT CUT, like every other cut on this board: the dropped boards ride
    #    an `anchor_cap` note that `render_board` prints as its own SB-X.
    #
    #    THE EXPLICIT GESTURES ARE RESERVED AND THE CUT FALLS ON THE UNBOUNDED SOURCES, which is not
    #    the same thing as cutting the precedence tail and is the correction a first draft of this
    #    ceiling needed. `ANCHOR_SOURCES` ranks `focus_driver` ABOVE `named` (Amendment 1's own order),
    #    so a plain tail cut would keep a driver's twenty-ninth board and DROP the market the user
    #    typed -- Amendment 2 defeated by the fence meant to bound Amendment 1. `attached_event` and
    #    `named` are already bounded (one gesture; `dispatch.NAMED_ANCHOR_CAP`), so they are kept whole
    #    and the seats that remain go to the two unbounded sources in their own precedence order. A
    #    turn whose gestures alone exceed the tier's ceiling raises it to them rather than dropping
    #    one, and says so by carrying no cut at all.
    #
    #    COLD START IS EXEMPT, and the exemption is structural rather than a carve-out. `board_loudest`
    #    PRICES THE READ SET FIRST and the anchors are a DESCRIPTION of where the admitted keys sit
    #    (`cold_start_keys` -> `priced['boards']`), so cutting the boards would leave wave 1's plan --
    #    which IS the priced set, in the priced order -- naming keys on boards the board no longer
    #    carries. The read budget there is already bounded by the pricer's own cap; what is NOT bounded
    #    is the tape column and the render, and that is a residual of a lane that ships dark (D26).
    #
    #    THE CUT IS BY THE GRAPH'S DECLARED ORDER, not by the state rank, and it must be: Amendment 1
    #    re-ranks a driver anchor set by that driver's own STATE, which does not exist until wave 1 has
    #    run -- and wave 1 is exactly what this cut exists to bound. `_driver_anchor_order`'s order
    #    (confidence, then the driver's own lag band, then slug) is deterministic and is the best
    #    ordering available before a read; `rank_driver_anchors` then re-ranks what survived.
    _amax = max(1, int(getattr(kn, "max_anchors", 0) or 0))
    if admit_order is None and len(bd.anchors) > _amax:
        def _explicit(a):
            return a.source in ("attached_event", "named") or bool(getattr(a, "named", False))

        _held = [a for a in bd.anchors if _explicit(a)]
        _rest = [a for a in bd.anchors if not _explicit(a)]
        _room = max(0, _amax - len(_held))
        _keep = set(id(a) for a in _held) | set(id(a) for a in _rest[:_room])
        _dropped = tuple(a.contract for a in bd.anchors if id(a) not in _keep)
        if _dropped:
            bd.anchors = tuple(a for a in bd.anchors if id(a) in _keep)
            bd.notes.append({"kind": "anchor_cap", "cap": _amax, "dropped": len(_dropped),
                             "held": len(_held), "names": _dropped})

    # ── THE READ CAPS ARE DECLARED HERE, AFTER THE ANCHOR GATE AND BEFORE THE FIRST FETCH, and the
    #    placement is the S6 review's fatal 2. They used to be set above the lane gate, so a board that
    #    DECLINED still carried cap 24 / 50 / 71 with `net_reads` 0 -- and `cascade._board_declared_cap`
    #    read that cap onto the walk's own ceiling on a turn `quantify` received no board at all.
    #    Declaring them here makes "the cap the board declared" and "the board ran" ONE fact rather
    #    than two that could disagree; `_board_declared_cap` gates on the leg as well, which is the
    #    belt to this brace.
    bd.ledger.waves[1].reads_cap = int(kn.wave1)
    # THE EFFECTIVE wave-2 cap, not the declared one: with leg B dark, Cascade's 58 is 31 (sec 3.8's
    # own "71 with leg B dark"). The ceiling the walk gains at S6 must be what the board can SPEND --
    # which is why `analog_reads` rides the same argument shape: a turn whose caller wires no
    # `benchmark_fn` and no `receipt_fn` can never spend those columns, and reserving them put up to 15
    # structurally unspendable reads on the walk's runaway tripwire (S6 review, major 7).
    bd.ledger.waves[2].reads_cap = int(
        B.wave2_shape(kn, legb_cells=legb_cells, legb_on=legb_on,
                      analog_reads=analog_reads)["total"])
    bd.stamp("board", "fired")

    # THE RULE IS ON THE BOARD, so no stage carries a second copy of the switch: `_stage1` and
    # `_stage2` both read `bd.rank_rule`, and a stage that ranked by an argument while the board said
    # otherwise is the drift this re-fix exists to make unspellable.
    _stage1(bd, graph, kn, key_fn=key_fn, state_fn=state_fn, turn_kind=turn_kind, width=width,
            positioning_ids=positioning_ids, admit_order=admit_order)
    if stage2:
        _stage2(bd, graph, kn, key_fn=key_fn, state_fn=state_fn, receipts=receipts, width=width,
                legb_cells=legb_cells, legb_on=legb_on, complexes=complexes, chains=chains,
                turn_kind=turn_kind, analog_reads=analog_reads)
    return bd


def stage2(bd: B.Board, graph, *, state_fn=None, key_fn=None, receipts=None, width: int = 2,
           legb_on: bool = False, complexes=(), chains=(), analog_reads: bool = True) -> B.Board:
    """STAGE 2 ALONE, on a board :func:`walk` built with ``stage2=False`` (D11, sec 3.9).

    IT EXISTS BECAUSE THE TWO STAGES RUN AT TWO SEAMS AND NOT ONE. `walk(stage2=True)` is the harness
    and census shape -- one call, both stages, no `ground()` in between. The SERVING shape is stage 1
    after `pl.grounded_subgraph` (the anchors exist, nothing is retrieved) and stage 2 after
    `pl.ground` (which is what fills `n.evidence`, i.e. the receipts stage 2 reads). A seam that
    reached into `_stage2` would be a second caller of a private function with eleven keyword
    arguments; this is the ONE public door, and it re-derives from the BOARD what the walk resolved
    once (`bd.knobs`, `bd.mode`, `bd.turn_kind`) rather than asking the caller to carry it a second
    time and risk carrying it differently.

    A BOARD WHOSE STAGE 1 NEVER RAN IS RETURNED UNTOUCHED, with its own words already on it: the walk
    stamps `lane_off` / `anchor_none` and returns before stage 1, and stage 2 over an anchorless board
    would price a wave against a rank that does not exist."""
    if bd.knobs is None or not bd.anchors or not bd.stage_done.get(1):
        return bd
    _stage2(bd, graph, bd.knobs, key_fn=key_fn, state_fn=state_fn, receipts=receipts, width=width,
            legb_cells=B.legb_cells_of(bd.mode), legb_on=legb_on, complexes=complexes, chains=chains,
            turn_kind=bd.turn_kind, analog_reads=analog_reads)
    return bd


def _stage1(bd, graph, kn, *, key_fn, state_fn, turn_kind, width, positioning_ids,
            admit_order=None) -> None:
    """STEPS 0-4 of sec 3.3: rows (0 reads), price wave 1 (0 reads), ONE wave, state, rank, loud set.

    ``admit_order`` is COLD START's priced positions (``{label: position}``); when present it replaces
    the `anchor board first` term for a key the pricer admitted, so the wave-1 cut IS the priced set.
    On every other turn it is ``None`` and the term is the anchor ordinal sec 3.8 declares."""
    t0 = time.perf_counter()
    key_fn = key_fn or _default_key_fn
    subject_driver = bd.subject_driver
    subject_slugs = {a.contract for a in bd.anchors if a.subject}

    # 0  rows = EVERY node of EVERY anchor DAG -- never filtered, whatever tier it lands in.
    priced, plans = [], {}
    for order, a in enumerate(bd.anchors):
        contract = (getattr(graph, "contracts", {}) or {}).get(a.contract)
        for d in (getattr(contract, "drivers", ()) or ()):
            row = _node_row(graph, a.contract, d)
            # POSITIONING AS SUBJECT (Amendment 1): `context_only` yields when the query names the
            # driver being explained. It is set on the ROW, so every consumer of the rule reads one
            # field rather than re-deriving the exception.
            if subject_driver and d.id == subject_driver and a.contract in subject_slugs:
                row.subject = True
            bd.rows.append(row)
            node = _WalkNode(a.contract, d)
            ref = str(getattr(d, "silver_ref", "") or "")
            if not ref:
                row.coverage_tier = _text_tier(row.silver_status)
                continue
            plan = key_fn(ref, node, turn_kind=("" if row.subject else turn_kind))
            plans[row.key] = (plan, node, ref)
            if plan.key is None:
                row.state = _absent_state(ref, plan.status)
                row.coverage_tier = _tier_for(plan, row.silver_status, plan.status)
                continue
            row.series_key = plan.key.label()
            row.context_only = bool(plan.context_only) and not row.subject
            seat = order if admit_order is None else admit_order.get(row.series_key, _UNADMITTED)
            priced.append(PricedKey(label=row.series_key, ref=plan.key.ref, contract=a.contract,
                                    driver_id=d.id, anchor_order=seat, share=0,
                                    confidence=CONFIDENCE_RANK.get(row.confidence, 1)))

    # 1  price -- the SHARE term is measured over the rows being priced THIS TURN.
    share: dict = {}
    for k in priced:
        share[k.label] = share.get(k.label, 0) + 1
    priced = [k._replace(share=share[k.label]) for k in priced]
    cut = price_wave1(priced, cap=int(kn.wave1))
    w1 = bd.ledger.waves[1]
    w1.plan_written(cut["plan"], declared=cut["declared"], deferred=cut["deferred"], free=cut["free"])
    if cut["deferred"]:
        bd.ledger.budget_capped += len(cut["deferred"])
        bd.notes.append({"kind": "budget_cap", "wave": 1, "pairs": _cut_pairs(cut["deferred"]),
                         "names": tuple(sorted({k.label for k in cut["deferred"]}))})

    # 2  wave 1 -- ONE atomic wave at width min(2, n) on the numbers bulkhead.
    guard = _WidthGuard()
    fetched = run_wave(cut["plan"], _fetch(state_fn, plans, bd), ledger=w1, width=width, guard=guard)
    bd.series.update({lbl: st for lbl, st in fetched.items() if st is not None})

    # 3  state / tiers / SB-X reasons -- 0 reads.
    declined_labels: dict = {}          # {label: the CLOSED series word that declined it}
    deferred_labels = {k.label for k in cut["deferred"]}
    for row in bd.rows:
        got = plans.get(row.key)
        if got is None or got[0].key is None:
            continue
        plan = got[0]
        if row.series_key in deferred_labels:
            row.state = _absent_state(plan.key.ref, "budget_cap")
            row.coverage_tier = _tier_for(plan, row.silver_status, "budget_cap")
            continue
        st = bd.series.get(row.series_key)
        if st is None:
            row.state = _absent_state(plan.key.ref, "read_error")
            row.coverage_tier = _tier_for(plan, row.silver_status, "read_error")
            declined_labels.setdefault(row.series_key, "read_error")
            continue
        row.state = st
        row.coverage_tier = st.coverage_tier
        row.band_crossed = _convention_hit(row) == 1
        if st.vintage_note:
            bd.ledger.replay_labelled += 1
        if status_word(st.status) in ("pool_exhausted", "pg_timeout"):
            bd.ledger.pool_declined += 1
            declined_labels.setdefault(row.series_key, status_word(st.status))
    # B1: `read` IS COUNTED FROM WHAT CAME BACK, not derived from the other three. The first build wrote
    # `read = max(0, declared - deferred - declined)`, which made `WaveLedger.closed` an IDENTITY: the
    # rectangle could only fail by over-subtraction, so a bar the module's own docstring calls
    # "unbreakable" was unfalsifiable. Counted from the returns, the assertion does work -- a plan key
    # that came back neither served NOR named breaks the rectangle, loudly, at the next `rectangle()`.
    plan_labels = {k.label for k in cut["plan"]}
    served = {lbl for lbl in plan_labels if lbl not in declined_labels and bd.series.get(lbl) is not None}
    w1.declined = len(declined_labels)
    w1.read = len({k.label for k in cut["free"]}) + len(served)
    # A BOARD WITH NO MAPPED REF AT ALL IS A LEG THE WALK NEVER ENTERED, not one that declined: stamping
    # `budget_cap` there would name a cut that never happened, and the S3 render owes that word a
    # sentence about DROPPED KEYS. Three outcomes, three different facts -- and the SAME error stood in
    # the all-declined branch until the S2 review MEASURED it: four drivers whose reads all returned
    # `pool_exhausted` stamped `series: declined:budget_cap` with `budget_capped == 0` and no
    # `budget_cap` note, i.e. a cut with an empty list of dropped keys. `_dominant_decline` prefers the
    # word the reads actually said whenever nothing was deferred; the honest word was already on the
    # ledger (`pool_declined`) and in `declined_labels`, and only the stamp was lying.
    if w1.read:
        bd.stamp("series", "fired", reads=w1.reads_used)
    elif w1.series_declared:
        bd.stamp("series", "declined", reads=w1.reads_used,
                 reason=_dominant_decline(declined_labels.values(), deferred=w1.deferred))
    else:
        bd.stamp("series", "not_reached")

    # AMENDMENT 1's ranking, which needs the state that now exists.
    rank_driver_anchors(bd)

    # 4  rank + the loud set -- the ONE ranking pass. Stage 2 appends and never re-ranks.
    #    THE STAMP IS THE SWITCH. Everything downstream (`board_order`, stage 2's re-taken loud set,
    #    the analog seats, the render's row order, the `board=` payload S6 threads) reads `row.rank`,
    #    so choosing the tuple HERE is what makes `alternative_rank` reach all of them.
    key = rank_key_for(bd.rank_rule)
    for row in bd.rows:
        row.rank = key(row)
    for row in loud_set(bd.rows, loud_k=int(kn.loud_k), alternative=bd.rank_rule):
        row.legs["loud"] = True
    board_order(bd)                      # sec 3.9 item 1 -- the ordered node list S6 threads
    bd.recency["width_peak"] = guard.peak
    bd.stage_ms[1] = (time.perf_counter() - t0) * 1000.0
    bd.stage_done[1] = True


def _stage2(bd, graph, kn, *, key_fn, state_fn, receipts, width, legb_cells, legb_on, complexes,
            chains, turn_kind, analog_reads: bool = True) -> None:
    """STEPS 5-14 of sec 3.3: receipts, EVENT rows, the closure, the edges, the free fan, wave 2's
    price, wave 2, convergence, complexes and chains. IT NEVER RE-RANKS STAGE 1."""
    t0 = time.perf_counter()
    key_fn = key_fn or _default_key_fn
    receipts = receipts or {}

    # 5  receipts + EVENT rows (sec 3.7). `n.evidence` does not exist before `ground()`.
    #    THE TWO ABSENCES ARE DIFFERENT FACTS AND THE ROW SAYS WHICH (rows.TEXT_STATUS_WORDS): a node
    #    the caller never fetched receipts for is `no_receipt_fetched`; a node that WAS filled and
    #    carries none is `no_receipts`. The first build wrote `no_receipts` whenever the list was empty,
    #    which collapsed the two and made the third word of a closed set unreachable from the walk --
    #    the very distinction rows.py:111 was declared this sitting to keep.
    for row in bd.rows:
        fetched_receipts = (row.key in receipts) or (row.driver_id in receipts)
        rs = receipts.get(row.key) or receipts.get(row.driver_id) or ()
        row.receipts = _receipt_summary(rs, fetched=fetched_receipts)
        ed, prec, winner = event_receipt_for(rs, bd.asof)
        row.event_date, row.event_precision = ed, prec
        row.event_receipt = winner
        row.event_open = event_is_open(ed, row.lag_band or parse_lag(""), bd.asof)

    # the loud set is RE-TAKEN, not re-ranked: an OPEN EVENT row joins by construction (sec 3.2), and it
    # could not be known before step 5. Every row's `rank` tuple is the one stage 1 computed -- under
    # the board's OWN rule, which this call names so the re-take reads the same tuple the cut did.
    loud = loud_set(bd.rows, loud_k=int(kn.loud_k), alternative=bd.rank_rule)
    for row in bd.rows:
        row.legs["loud"] = row in loud
    loud_by_board: dict = {}
    for r in loud:
        loud_by_board.setdefault(r.contract, []).append(r)

    # 6  paths -- the FULL closure on every tier; only the RENDER is capped (D27).
    seen_paths = set()
    for r in loud:
        for p in ancestor_paths(graph, bd, r.contract, r.driver_id):
            ident = (p["contract"], p["ancestor"], p["bottom"])
            if ident in seen_paths:      # the same row arrived at from the other end
                continue
            seen_paths.add(ident)
            bd.paths.append(p)
    bd.paths.sort(key=lambda p: p["rank"])
    for i, p in enumerate(bd.paths):
        p["rendered"] = i < int(kn.path_render_k)
        p["decline"] = None if p["rendered"] else "render_cap"
    cut_paths = [p for p in bd.paths if not p["rendered"]]
    if cut_paths:
        bd.notes.append({"kind": "path_render_cap",
                         "names": tuple(p["ancestor"] for p in cut_paths)})
    bd.stamp("path", "fired" if any(p["rendered"] for p in bd.paths) else
             ("declined" if bd.paths else "not_reached"),
             reason="render_cap" if (bd.paths and not any(p["rendered"] for p in bd.paths)) else "")

    # 7  edges both ways, with the tier's own direction set (sec 3.5 / sec 7).
    # THROUGH `base_mode`, not a name split: a second base-preset resolver in the estate is the
    # duplicate-and-drift class, and the knob table already joins on that one function.
    from leviathan.graphrag import reasoning_modes as _rm
    directions = EDGE_DIRECTIONS.get(_rm.base_mode(bd.mode), ("forward", "reverse"))
    boards = list(bd.anchor_slugs)
    for slug in boards:
        bd.edges.extend(cross_edges(graph, slug, directions))
    skipped = tuple(d for d in ("forward", "reverse") if d not in directions)
    if skipped:
        bd.notes.append({"kind": "edge_hop_cap", "directions": skipped})
    # A board that declares NO inter-commodity edge is a leg the walk did not enter, not a leg that
    # declined: the closed `edge:` enum of sec 6.7 has words for a missing SIGN, an unparsed LAG and a
    # far series in another table, and none of them means "there was nothing here". Inventing one would
    # widen a vocabulary the S3 render owes a sentence per word.
    bd.stamp("edge", "fired" if bd.edges else "not_reached")

    # 8  the fan INDEX is FREE: every row with a shared id, loud or not, names its far boards.
    #    THE SEEDING ROW'S OWN WAVE-1 RANK POSITION rides every far key it mints (sec 3.3 step 9: far
    #    keys are "priced from the wave-1 rank"; sec 3.6: bounded "by the rank cut and the mode's
    #    fan_k"). At the S2 landing every far key was minted with `anchor_order=1, share=1`, so
    #    `wave1_order` collapsed to `(1, -1, -confidence, ref, label)` and the seeding row's rank was
    #    DISCARDED -- MEASURED on a hermetic graph with far cap 4: the anchor's z=5.0 row had all four
    #    of its far boards deferred while the z=0.02 row's four took the whole column, purely because
    #    the quiet row's far edges declared `high` confidence. The far half of the wave was ordered by
    #    the far graph's own confidence and by nothing about how loud the anchor row was.
    rank_seat = {k: i for i, k in enumerate(bd.order)}
    index = fan_index(graph)
    far_priced = []
    for row in bd.rows:
        fr = far_rows(index, row.contract, row.driver_id)
        if not fr:
            continue
        row.boards_sharing = tuple((f["contract"], f["sign"], f["lag"], f["confidence"], f["ref"])
                                   for f in fr)
        entry = {"contract": row.contract, "driver_id": row.driver_id, "loud": bool(row.legs.get("loud")),
                 "far": fr}
        bd.fan.append(entry)
        if not row.legs.get("loud") or row.context_only:
            continue
        # 9  ONLY a LOUD row's far STATES are priced, and only the first `fan_k` of them.
        #    A `context_only` ROW IS NEVER A FAN SOURCE (sec 2.4 / D18: "never a fan source, convergence
        #    member, analog dimension or projection anchor"). Its far boards are still NAMED above --
        #    `bd.fan` carries the entry -- because naming costs nothing and the index is free; what D18
        #    forbids is SPENDING a far read on it and letting a positioning row pull other boards' states
        #    onto this page. MEASURED at this landing: `cot_mm_positioning` sat in the scenario-1 loud
        #    set and priced far keys like any driver.
        for i, f in enumerate(fr):
            if i >= int(kn.fan_k):
                f["decline"] = "fan_cap"
                continue
            if not f["ref"]:
                f["decline"] = "board_unlabeled"
                continue
            far_d = _driver_of(graph, f["contract"], f["driver_id"])
            if far_d is None:
                f["decline"] = "child_uncovered"
                continue
            node = _WalkNode(f["contract"], far_d)
            plan = key_fn(f["ref"], node, turn_kind=turn_kind)
            if plan.key is None:
                f["decline"] = ("far_series_other_table" if plan.status.startswith("unmapped")
                                else None)
                continue
            f["series_key"] = plan.key.label()
            # A far state whose SERIES KEY IS ALREADY ON THE BOARD costs nothing: that is the memo, and
            # it is exactly how a globally-keyed ref (`oni_climate`) and a same-table lagged column
            # (`oni_lag_climate` through `same_series_as`) join a far board to the anchor's own reading
            # at ZERO extra reads (sec 3.6). The row then POINTS AT the same StateRow and says so.
            f["free"] = f["series_key"] in bd.series
            far_priced.append(PricedKey(label=f["series_key"], ref=plan.key.ref,
                                        contract=f["contract"], driver_id=f["driver_id"],
                                        anchor_order=rank_seat.get(row.key, len(bd.order)), share=0,
                                        confidence=CONFIDENCE_RANK.get(f["confidence"], 1),
                                        free=f["free"]))
            if f["free"]:
                f["state_read"] = True
    # The SHARE term, measured over the far keys being priced THIS turn exactly as wave 1 measures its
    # own: a far key several loud rows all want is bought once and outranks a key one row wants. It was
    # a constant 1 in wave 2, i.e. the fan-out weighting sec 3.8 names was absent from the wave it was
    # written for. `dedup_by_label` then prices the KEY at the seat of its LOUDEST seeding row.
    far_share: dict = {}
    for k in far_priced:
        far_share[k.label] = far_share.get(k.label, 0) + 1
    far_priced = [k._replace(share=far_share[k.label]) for k in far_priced]
    bd.stamp("fan", "fired" if bd.fan else "not_reached")

    # SB-X (sec 3.2's own line): "the rows past this mode's cut whose far STATES were not read". Every
    # other cut on this board mints a note (`budget_cap`, `path_render_cap`, `edge_hop_cap`); this one
    # had no producer at the S2 landing, so the one SB-X line the design specifies per mode had nothing
    # to read. The far NAMES are never cut -- this note is about STATES only (sec 3.6).
    unread_fan = tuple(sorted({(e["contract"], e["driver_id"]) for e in bd.fan
                               if not e["loud"] and any(f["ref"] for f in e["far"])}))
    if unread_fan:
        bd.notes.append({"kind": "fan_states_unread", "loud_k": int(kn.loud_k),
                         "rows": len(unread_fan), "names": unread_fan})

    # 10 price wave 2 -- AFTER the rank, BEFORE its own fetch. The analog columns are S3's to fill; the
    #    board prices the seats now so the rectangle is closed whether or not S3's leg runs.
    # THE TWO ANALOG COLUMNS ARE RESERVED ONLY WHEN THEIR PRODUCER IS WIRED (S6 review, major 7). The
    # reads are made by `analogs._outcomes_for` / `_receipts_for` through an INJECTED `benchmark_fn` /
    # `receipt_fn`; phase 2's seam wires neither, so those seats were 3-15 reads a turn that no producer
    # could spend, reserved against the cap and carried onto the WALK's ceiling. `analog_reads` follows
    # leg B's rider exactly: the declared cells set the residual, the rider sets whether the column is
    # spent. The seats are still RECORDED (`Ledger.evidence_cap` / `benchmark_cap`) so a budget term is
    # never merely absent.
    bench = [f"analog_benchmark:{r.contract}:{r.driver_id}" for r in loud[:int(kn.analog_dims)]
             for _ in range(int(kn.analog_k))] if analog_reads else []
    recs = [f"analog_receipt:{r.contract}:{r.driver_id}" for r in loud[:int(kn.analog_dims)]
            for _ in range(int(kn.analog_k))] if analog_reads else []
    p2 = price_wave2(far_keys=far_priced, analog_benchmarks=bench, analog_receipts=recs,
                     legb_cells=legb_cells, legb_on=legb_on, knobs=kn)
    w2 = bd.ledger.waves[2]
    dropped = tuple(x for col in p2["deferred"].values() for x in col)
    # THE RECTANGLE IS OVER WHAT THIS WAVE EXECUTES (see `price_wave2`'s note): the far keys. The analog
    # seats are reserved against the cap and recorded below, and S3's analog leg extends the rectangle
    # in the sitting that spends them.
    w2.plan_written(p2["plan"], declared=p2["far_declared"], deferred=p2["far_deferred"],
                    free=p2["free"])
    bd.notes.append({"kind": "wave2_reserved", "columns": {
        k: len(v) for k, v in p2["columns"].items() if k != "far"}})
    if dropped:
        bd.ledger.budget_capped += len(dropped)
        bd.notes.append({"kind": "budget_cap", "wave": 2, "pairs": _cut_pairs(dropped),
                         "names": tuple(sorted({getattr(x, "label", str(x)) for x in dropped}))})
    dropped_labels = {getattr(x, "label", "") for x in dropped}
    for e in bd.fan:
        for f in e["far"]:
            if f["series_key"] and f["series_key"] in dropped_labels and not f["free"]:
                f["decline"] = "fan_cap"

    # 11 wave 2 -- the second atomic wave, same bulkhead, same width.
    far_plans = {}
    for e in bd.fan:
        for f in e["far"]:
            if f["series_key"]:
                far_d = _driver_of(graph, f["contract"], f["driver_id"])
                if far_d is not None:
                    far_plans[(f["contract"], f["driver_id"])] = (
                        key_fn(f["ref"], _WalkNode(f["contract"], far_d), turn_kind=turn_kind),
                        _WalkNode(f["contract"], far_d), f["ref"])
    guard = _WidthGuard()
    got2 = run_wave(p2["plan"], _fetch(state_fn, far_plans, bd), ledger=w2,
                    width=width, guard=guard)
    bd.series.update({lbl: st for lbl, st in got2.items() if st is not None})
    for e in bd.fan:
        for f in e["far"]:
            if f["series_key"] and f["series_key"] in bd.series:
                f["state_read"] = True
    # A FAR READ THAT DECLINED BY NAME IS COUNTED, exactly as wave 1's is: `BoardPoolDeclined` is arm
    # A's bar and its bar is 0, so a decline the ledger never saw would make the bar unmeasurable.
    # B1 AGAIN: `read` is COUNTED from what came back (the served plan labels plus the free ones), never
    # derived from the other three -- see the same note in `_stage1`.
    plan2 = {k.label for k in p2["plan"]}
    served2 = {lbl for lbl in plan2
               if got2.get(lbl) is not None
               and status_word(got2[lbl].status) not in ("pool_exhausted", "pg_timeout")}
    far_declined = plan2 - served2
    w2.declined = len(far_declined)
    bd.ledger.pool_declined += sum(
        1 for lbl, st in got2.items()
        if st is not None and status_word(st.status) in ("pool_exhausted", "pg_timeout"))
    w2.read = len({k.label for k in p2["free"]}) + len(served2)
    # THE SEATS, NEVER THE READS (S6 review, major 6). `evidence_borrows` used to be assigned this
    # number and `state.seam.counters` published it as `BoardEvidenceBorrows`, whose 10.5 definition is
    # "analog receipt reads on the evidence pool" -- MEASURED at 3 on every fired Analysis board and 5
    # on every fired Cascade board while `_receipts_for` returned [] at zero reads, because the seam
    # wires no `receipt_fn`. Arm A's evidence-pool pressure would have been read off a number no read
    # produced. The RESERVATION is a cap and is recorded as one; the BORROWS are counted by the one
    # producer that makes them, in `analogs`.
    bd.ledger.evidence_cap = len(p2["columns"]["analog_receipts"])
    bd.ledger.benchmark_cap = len(p2["columns"]["analog_benchmark"])

    # 12 convergence as ORDERING WORDS, per touched board (sec 3.5, D24).
    #    `band_ids` IS THIS BOARD'S OWN, not the estate's: a board-WIDE id set (what the first build
    #    passed) counts a band crossed on board A toward board B's pattern row on a multi-anchor turn,
    #    because a pattern's driver ids are bare ids and two boards can declare the same one.
    n_amp = 0
    for slug in boards:
        # A `context_only` ROW IS NEVER A CONVERGENCE MEMBER (D18). MEASURED at this landing: the
        # scenario-1 harness rendered "South American weather squeeze: two of its five declared drivers
        # sit among this board's loudest rows (psd ending stock su ratio, cot mm positioning)" -- a
        # pattern counted as two-of-five on the strength of a POSITIONING row, which is exactly the
        # reading the R9 guard's measured failure was about.
        ids = {r.driver_id for r in loud_by_board.get(slug, ()) if not r.context_only}
        banded = {r.driver_id for r in bd.rows if r.contract == slug and r.band_crossed}
        # WHICH OF THOSE IDS THIS BOARD ACTUALLY READ. The pattern row's COUNT is the ordering fact and
        # stays the loud intersection; the NAMES it lists as carrying an `[N]` z have to be the ones
        # that do (sec 6.2's own template), and only the walk knows which those are.
        read_ids = {r.driver_id for r in loud_by_board.get(slug, ())
                    if not r.context_only and r.state is not None
                    and status_word(r.state.status) == "ok"}
        rows = convergence_rows(graph, slug, ids, loud_k=int(kn.loud_k), band_ids=banded,
                                measured_ids=read_ids)
        bd.convergence.extend(rows)
        n_amp += sum(1 for r in rows for i in r["interactions"] if i["rendered"])
    bd.stamp("interaction", "fired" if n_amp else
             ("declined" if any(r["interactions"] for r in bd.convergence) else "not_reached"),
             reason="" if n_amp else ("when_not_all_loud" if any(r["interactions"] for r in
                                                                 bd.convergence) else ""))

    # 13 complexes and chains as declared paths / vocabulary. `loud_boards` is what makes a chain's
    #    LOUD hops loud rather than merely present (sec 3.5: "ordered by the number of loud hops").
    on_board = set(bd.anchor_slugs) | {f["contract"] for e in bd.fan for f in e["far"]}
    loud_boards = set(loud_by_board)
    bd.notes.append({"kind": "complexes", "rows": tuple(
        (tuple(c["pair"]), c["rendered"]) for c in complex_pairs(complexes, on_board))})
    bd.notes.append({"kind": "chains", "rows": tuple(
        (c["name"], c["rendered"], c["loud_hops"])
        for c in chain_paths(chains, on_board, loud_boards=loud_boards))})

    # 14 the windows the board hands `quantify` (sec 3.9 item 2) and the recency ledger's own facts.
    for r in bd.rows:
        st = r.state
        if st is None or not r.legs.get("loud"):
            continue
        near = ((st.run or {}).get("since_date") if st.run and not st.run.get("declined") else None) \
            or st.level_date
        bd.windows[r.key] = {"near": near, "state_date": st.level_date,
                             "knowledge_date": st.knowledge_date, "analog_dates": ()}
    # sec 3.9 item 1 again -- and it is NOT a re-rank of stage 1. The numeric head reads the tuple stage
    # 1 stamped (`stored_rank`); only the TEXT-ONLY tail moves, and sec 3.2 says in so many words that
    # its order "is computed in STAGE 2", because `newest receipt date` does not exist before `ground()`.
    board_order(bd)
    bd.recency["numbers"] = max((st.knowledge_date or "" for st in bd.series.values()), default="")
    bd.recency["text"] = max(((r.receipts or {}).get("newest_date") or "" for r in bd.rows), default="")
    bd.recency["width_peak"] = max(bd.recency.get("width_peak", 0), guard.peak)
    bd.stage_ms[2] = (time.perf_counter() - t0) * 1000.0
    bd.stage_done[2] = True


# ---------------------------------------------------------------------------------------------------
# the injected seams
# ---------------------------------------------------------------------------------------------------
def _default_key_fn(ref, node, *, turn_kind: str = ""):
    from leviathan.graphrag.state import feeders as F
    return F.series_key_for(ref, node, turn_kind=turn_kind)


def _fetch(state_fn, plans: dict, bd):
    """Bind ONE :class:`PricedKey` to the injected producer. ``state_fn(ref, node) -> (StateRow, reads)``.

    THE HANDLER NEVER RAISES -- ``feeders.series_state``'s own contract, kept here because a read that
    breaks an answer is worse than a read that declines by name."""
    def _one(k: PricedKey):
        got = plans.get((k.contract, k.driver_id))
        if got is None:
            return None, 0
        _plan, node, ref = got
        if state_fn is None:
            return None, 0
        try:
            row = state_fn(ref, node)
        except Exception:                               # noqa: BLE001
            return None, 1
        if isinstance(row, tuple):
            row, reads = row
        else:
            reads = getattr(row, "reads", 1) or 0
        return row, int(reads)
    return _one


def _node_row(graph, contract: str, d) -> B.NodeRow:
    """One :class:`board.NodeRow` from the DAG's own Driver -- the fourteen fields VERBATIM."""
    live = False
    try:
        live = bool(graph.silver_status(contract, d.id).get("live"))
    except Exception:                                   # noqa: BLE001 -- a DISPLAY fact only (sec 1.3)
        live = False
    children = ()
    try:
        children = tuple(sorted(k for k, v in graph.descendants_by_depth(contract, d.id).items()
                                if v == -1))
    except Exception:                                   # noqa: BLE001
        children = ()
    return B.NodeRow(
        contract=contract, driver_id=d.id, type=getattr(d, "type", "") or "",
        sign=getattr(d, "sign", "") or "", mechanism=getattr(d, "mechanism", "") or "",
        blurb=getattr(d, "blurb", None), lag=getattr(d, "lag", "") or "",
        region=getattr(d, "region", None), edge_type=getattr(d, "edge_type", "causes") or "causes",
        target_metric=getattr(d, "target_metric", None),
        silver_ref=getattr(d, "silver_ref", None),
        silver_status=getattr(d, "silver_status", "none") or "none",
        parents=tuple(getattr(d, "parents", ()) or ()),
        evidence_query=getattr(d, "evidence_query", "") or "",
        confidence=getattr(d, "confidence", "medium") or "medium",
        lag_band=parse_lag(getattr(d, "lag", "")), children=children, live=live,
        coverage_tier=_text_tier(getattr(d, "silver_status", "none")))


def _text_tier(silver_status: str) -> str:
    return {"available": "declared_available_unserved",
            "planned": "planned_text_only"}.get((silver_status or "none").strip(), "none_text_only")


def _tier_for(plan, silver_status: str, status: str) -> str:
    from leviathan.graphrag.state.rows import coverage_tier
    return coverage_tier(map_row=plan.row, silver_status=silver_status, status=status)


def _absent_state(ref: str, status: str) -> StateRow:
    """An ABSENCE AS A ROW (sec 1.3). The StateRow exists, carries the closed word and spends nothing --
    the render owes it a sentence and the reader is never shown a silence."""
    from leviathan.graphrag.state.rows import SeriesKey
    return StateRow(key=SeriesKey(ref=ref), status=status, reads=0)


def _receipt_summary(rs, *, fetched: bool = True) -> dict:
    """``TextState.summary()``'s shape, with the THIRD closed word reachable (rows.TEXT_STATUS_WORDS).

    ``fetched`` is whether the caller's receipt map carried an entry for this node at all -- the
    difference between "phase 1b retrieved none this turn" (``no_receipt_fetched``) and "this node was
    filled and has none" (``no_receipts``). Two words, two sentences the S3 render owes, and the walk
    is the only place that knows which one is true."""
    dates = sorted(str((r.get("date") if isinstance(r, dict) else getattr(r, "date", "")) or "")
                   for r in (rs or ()) if r)
    dates = [d for d in dates if d]
    return {"n": len(rs or ()), "newest_date": dates[-1] if dates else None,
            "oldest_date": dates[0] if dates else None,
            "top": [dict(r) if isinstance(r, dict) else {"date": getattr(r, "date", "")}
                    for r in list(rs or ())[:3]],
            "status": "ok" if rs else ("no_receipts" if fetched else "no_receipt_fetched")}
