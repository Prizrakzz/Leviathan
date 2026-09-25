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

import bisect
import re
import threading
import time
from dataclasses import dataclass, field, replace
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple, Optional

from leviathan.graphrag.numbers import stats as ST
from leviathan.graphrag.state import board as B
from leviathan.graphrag.state.analogs import axis_date
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
    specificity is never a circular input to who got retrieved (sec 3.2).

    **A LEVEL WHOSE PERIOD IS BEHIND ONE ALREADY HELD SITS ONE BAND LOWER** (CONTRACT C11, the
    2024-03-01 as-of turn: the PSD area and stocks-to-use rows read marketing year 2020/21 while newer
    years of the same sheet had been published, and ranked beside readings of the present). The fact is
    lane C's -- ``StateRow.period_gap``, stamped by ``feeders.stamp_period_gaps`` ONLY where a sibling
    series of the same slug on the same card came back holding a NEWER period as known at the as-of (a
    fact about the store; the card's ``period_first_known`` numbers never decide it -- the 09-23
    verifier's F1), and EMPTY everywhere else -- and this function only READS it: a non-empty gap is one band
    lower, so a three-year-old level is never ordered as "now". **THE STORE-PERIOD STAMP DEMOTES THE
    SAME ONE BAND** (CONTRACT K23, the 09-24 re-smoke's item 13): ``StateRow.period_behind`` -- lane C's
    fact that the store HOLDS a newer period of the same commodity and scope on another served
    marketing-year card as known at the as-of (the 2024-03-01 turn read the PSD MY2020 stocks-to-use as
    the buffer beside WASDE's 2023/24) -- is read the same defensive way, and the two stamps never
    stack: a row behind on both counts is one band lower, once. IT IS A DEMOTION AND NEVER A REMOVAL
    (W-12): the row keeps its state, its rank tuple and its render, and the page states the gap in its
    own words. THE DEMOTION STAYS INSIDE THE NUMERIC TIER (bands 0-2): a gapped row still carries a
    reading, and the text-only tier's order (:func:`text_tier_key`) is a rule about receipts that a
    served level must never be sorted by. So a band-2 row -- a level with no standing -- is already at
    the numeric floor and does not move. Read defensively (``getattr``): a StateRow built before the
    field existed carries no gap, which is exactly HEAD's reading."""
    tier = row.coverage_tier
    if tier in ("series", "series_thin"):
        st = row.state
        if st is not None and _ok(st.z):
            band = 0
        elif st is not None and _ok(st.percentile):
            band = 1
        else:
            band = 2
        if st is not None and (getattr(st, "period_gap", None) or getattr(st, "period_behind", None)):
            band = min(band + 1, 2)
        return band
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
def question_reach(graph, *, named=(), planned=()) -> tuple:
    """**THE QUESTION'S REACH** (CONTRACT K9, the 09-24 re-smoke's item 15) -- ``((slug, distance), ...)``.

    Distance 0 is the question's OWN contracts: the markets it named and the ones the planner planned
    for it. Distance 1 is every loaded contract that DRIVES a distance-0 contract by a declared
    inter-commodity edge -- ``graph.cross_links(c)`` (graph.py:378, "the boards that DRIVE this one"),
    the edge's resolved ``target_contract`` or, where the declared commodity is itself a loaded
    contract, that contract. NEVER the boards a question market cascades INTO (``graph.rev_cross_links``,
    graph.py:415): those are consequences of the question's market, not causes of it, and a subject
    chain anchored there does not run INTO the question. MEASURED on the local graph for the ten 09-24
    turns (CONTRACT K9's table): cocoa reaches {cocoa}; the soybean turns reach soybeans_cbot's crush and
    feed complex; arabica_coffee, brazilian_arabica_coffee and campinas_corn_reference_bmf are in no
    turn's reach (the last is a board soybeans cascades into -- reverse only).

    IT IS A GRAPH FACT AND NOTHING ELSE: zero reads, no state, no environment, no id named anywhere --
    which is why it replaces the rejected allowlist of "home boards" and the rejected stop-list of
    generic driver ids. Ordered by (distance, slug) and deterministic; a contract declared at distance
    0 is never re-listed at 1. An edge whose target is not a loaded contract is not a board and is not
    in reach. An unknown distance-0 contract keeps its seat (the question named it) and simply has no
    distance-1 neighbours."""
    zero: list = []
    for c in tuple(named or ()) + tuple(planned or ()):
        s = str(c or "").strip()
        if s and s not in zero:
            zero.append(s)
    loaded = set(getattr(graph, "contracts", {}) or {}) if graph is not None else set()
    one: set = set()
    for c in zero:
        try:
            edges = graph.cross_links(c) if graph is not None else ()
        except Exception:                               # noqa: BLE001 -- cross_links KeyErrors on an
            edges = ()                                  # unknown contract; the named seat stands alone
        for e in (edges or ()):
            other = str(e.get("target_contract") or e.get("driver_commodity") or "")
            if other and other in loaded and other not in zero:
                one.add(other)
    return tuple((s, 0) for s in sorted(zero)) + tuple((s, 1) for s in sorted(one))


def subject_anchor_plan(graph, subject=(), *, expand: bool = True, reach=None) -> tuple:
    """``((slug, order_key, ids_on_that_board), ...)`` for a resolved subject, in the GRAPH's declared
    order. Pure: zero reads, no state, no environment, and deterministic on every tie.

    THE PICKS ARE EXPANDED TO THEIR GROUPS FIRST (SUBJECT RESOLVER D4). The planner names ONE id and
    the estate carries four ids for fertilizer, three for crude, three for EUDR and five for
    positioning -- different ids on different boards for one concept -- so an unexpanded pick answers
    on the boards that happened to spell it that way and silently misses the rest. ``expand=False`` is
    the deck's seat for measuring the difference, never a configuration.

    THE ORDER IS ``_driver_anchor_order``'s, per id, merged by BEST key then slug. Not a per-id
    concatenation: two ids of one group would then rank every board of the first ahead of every board
    of the second, and the anchor ceiling would cut by alphabet. One board, one seat, best key wins.

    **``reach`` BOUNDS THE GROUP TO THE QUESTION'S OWN MARKETS** (CONTRACT K9, the 09-24 re-smoke's
    item 15). The group expansion carried a generic id -- the stocks-to-use group, the Brazil-supply
    group -- onto EVERY board that declares it, and the tier's anchor cap kept the head of this order,
    whose tie-break is the SLUG: cocoa, cotton and rice all anchored arabica_coffee,
    brazilian_arabica_coffee, barley, campinas_corn_reference_bmf and canola_ice, the top chain on cocoa
    and rice was Brazilian arabica into robusta, and the soybean turns' subject seat was a safrinha CORN
    chain. With ``reach`` (:func:`question_reach`'s pairs) a subject id anchors ONLY a board in reach,
    and the order leads with the board's DISTANCE -- the question's own markets first, then the boards
    that drive them -- before the driver's declared confidence and lag, the slug LAST. ``reach=None`` is
    HEAD's unbounded plan, kept for the offline harness and the deck that measures the difference; an
    EMPTY reach anchors nothing, because a question with no market of its own has nothing for a subject
    to be bounded by (a board turn always has one -- D26's empty route never reaches the board)."""
    ids = tuple(str(i) for i in (subject or ()) if str(i or "").strip())
    if not ids or graph is None:
        return ()
    if expand:
        try:
            from leviathan.graphrag.state import subject as SUBJ
            ids = SUBJ.expand_group(ids, graph) or ids
        except Exception:                               # noqa: BLE001 -- no group table is not an error;
            pass                                        # the picks themselves are the honest fallback
    dist = None if reach is None else {str(s): int(d) for s, d in (reach or ())}
    best: dict = {}
    carried: dict = {}
    for did in sorted(ids):
        for slug, key in _driver_anchor_order(graph, did):
            if dist is not None:
                if slug not in dist:
                    continue
                key = (dist[slug],) + tuple(key)
            carried.setdefault(slug, set()).add(did)
            if slug not in best or key < best[slug]:
                best[slug] = key
    return tuple((slug, best[slug], tuple(sorted(carried[slug])))
                 for slug in sorted(best, key=lambda s: (best[s], s)))


def resolve_anchors(*, contracts=(), named=(), attached_event: Optional[str] = None,
                    focus_driver: str = "", graph=None, max_contracts: int = 2,
                    positioning_ids=(), cold_start: bool = False, cold_start_priced=None,
                    cold_start_knobs: Optional[B.BoardKnobs] = None, key_fn=None,
                    subject=()) -> tuple:
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
      2b. **A RESOLVED SUBJECT ANCHORS ITS GROUP** (SUBJECT RESOLVER D6), in `focus_driver`'s own
         shape: every contract carrying any id of the subject's group, in the graph's declared order,
         exempt from `max_contracts` for exactly the reason a `focus_driver` set is -- those contracts
         are not PLANNED, they are read off the graph -- and bounded by the tier's own
         `BoardKnobs.max_anchors`, which `walk()` applies AFTER this function and which holds only the
         EXPLICIT sources. A subject is an inference about a typed phrase, so it is cut before an
         attachment and before a market the user named, which is the doctrine and not a convenience.
         **AN FE `focus_driver` OUTRANKS IT AND NEVER SILENCES IT**: when both are present and DIFFER,
         BOTH anchor (the precedence orders them) and `Board.trace()['subject']['vs_focus']` says
         `differ`. A silent override is the exact class `Anchor.named` was added to close.
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

    def _add(slug, source, *, rank=0, driver_id="", subject=False, group=(), note=""):
        slug = str(slug or "").strip()
        if not slug:
            return
        prior = picked.get(slug)
        # `named` IS MONOTONIC ACROSS THE COLLAPSE, and that is the whole reason it is a field rather
        # than a source word: the precedence ranks `focus_driver` above `named`, so a market the user
        # TYPED which also carries the attached driver would otherwise keep no record of having been
        # typed -- and the anchor ceiling would cut it in favour of the driver's own tail.
        was_named = bool(prior is not None and prior.named) or source == "named"
        # `group` IS MONOTONIC ACROSS THE COLLAPSE for the same reason `named` is: the precedence ranks
        # `focus_driver` ABOVE `subject`, so a board that is BOTH -- the driver the user attached, on a
        # board the resolved subject's group also reaches -- would otherwise keep no record of which
        # subject id it carries, and the render could not say which name it answered under.
        was_group = tuple(sorted(set(getattr(prior, "group", ()) or ()) | set(group or ())))
        if prior is not None and B.ANCHOR_SOURCES.index(prior.source) <= B.ANCHOR_SOURCES.index(source):
            if (was_named and not prior.named) or was_group != tuple(prior.group or ()):
                picked[slug] = replace(prior, named=was_named or prior.named, group=was_group)
            return
        picked[slug] = B.Anchor(contract=slug, source=source, rank=rank, driver_id=driver_id,
                                subject=subject, named=was_named, group=was_group, note=note)

    if attached_event:
        _add(attached_event, "attached_event", note="attached to the question")

    if focus_driver and graph is not None:
        # RENAMED FROM `subject` AT THE RESOLVER LANDING, and the rename is load-bearing rather than
        # tidy: this line REBOUND the function's own `subject` parameter -- the picked driver ids --
        # to a BOOL, so every subject anchor below silently disappeared on any turn that also carried
        # an FE `focus_driver`. Two facts, one name, and the collision was invisible because both
        # values are truthy-looking. The `Anchor` FIELD is still `subject` (positioning's
        # `context_only` exception, Amendment 1); only this local moves.
        _fd_is_subject = str(focus_driver) in set(positioning_ids or ())
        for i, (slug, _terms) in enumerate(_driver_anchor_order(graph, focus_driver)):
            _add(slug, "focus_driver", rank=i, driver_id=str(focus_driver), subject=_fd_is_subject,
                 note="carries the driver the question names")

    # THE RESOLVED SUBJECT, ADDED BEFORE THE INFERRED LOOP AND THAT IS THE EXEMPTION. `inferred` below
    # is `contracts` MINUS what is already picked, so a board anchored here never spends one of
    # `max_contracts`' seats -- the same structural exemption `focus_driver` gets, expressed the same
    # way rather than by a second carve-out.
    #
    # **AND IT ANCHORS ONLY INSIDE THE QUESTION'S REACH** (CONTRACT K9). The reach is read off the walk's
    # own anchor inputs -- the markets the question NAMED (and an attached event, the explicit gesture
    # that names one), the contracts the planner PLANNED -- plus the boards that drive them by a declared
    # edge; zero reads. It is computed ONLY when a subject reached this call, so every turn the resolver
    # does not reach takes S6's branch and every anchor keeps `distance=None` (B4).
    _pos = set(positioning_ids or ())
    _subj = tuple(str(i) for i in (subject or ()) if str(i or "").strip())
    _reach = (question_reach(graph, named=tuple(named or ()) + ((attached_event,) if attached_event
                                                                else ()),
                             planned=tuple(contracts or ()))
              if (_subj and graph is not None) else None)
    for i, (slug, _key, _ids) in enumerate(subject_anchor_plan(graph, _subj, reach=_reach)):
        _add(slug, "subject", rank=i, driver_id=(_ids[0] if len(_ids) == 1 else ""),
             subject=bool(_pos & set(_ids)), group=_ids,
             note="carries the driver the question is about")

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

    # THE ORDER IS `ANCHOR_ORDER`'s AND NOT THE PRECEDENCE'S (SUBJECT RESOLVER D6 amendment). The two
    # were one tuple until the resolver landed, and reading the precedence as the position put the
    # subject's thirty-four fan-out boards AHEAD of the board the question named -- measured on D6's
    # own example ("what does the pacific warming do to corn" opened on `robusta_coffee`, with
    # `corn_cbot` in the last surviving seat at every tier). The precedence still decides the WORD and
    # the trim; `ANCHOR_ORDER` decides who leads. With no subject the two agree seat for seat.
    if _reach is not None:
        # EVERY ANCHOR CARRIES ITS DISTANCE IN THE QUESTION'S REACH (K9) -- 0 for the question's own
        # markets, 1 for a board driving one, None for a board outside it (an FE gesture's own board). It
        # is how the walk knows the distance-0 set after the precedence collapse has folded a planned
        # seed into a `subject` anchor, and it is stamped only where a reach was computed.
        _d = {s: d for s, d in _reach}
        picked = {s: replace(a, distance=_d.get(s)) for s, a in picked.items()}
    return tuple(sorted(picked.values(), key=B.anchor_order_key))


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
    """AMENDMENT 1's ranking, applied AFTER wave 1: a DRIVER anchor set is ordered by THAT DRIVER'S
    OWN STATE on each contract (the 3.2 tuple over the driver's row on that board).

    IT RUNS IN STAGE 1 AND NOT AT ANCHOR TIME because the state does not exist at anchor time, and a
    ranking asserted before its input is a ranking of the alphabet. Anchors from every other source
    keep their arrival order -- that order is the planner's, and the board does not re-plan.

    BOTH DRIVER SOURCES, ONE PASS EACH (SUBJECT RESOLVER D6 amendment). This function filtered
    ``a.source == "focus_driver"`` twice over, so a RESOLVED subject's boards kept the graph-declared
    order the anchor pass gave them and the amendment's "then the subject's OTHER boards ranked by the
    subject driver's own state after wave 1" had no producer. Each source is ranked against its own
    driver and inside its own block: the two never interleave, because :data:`board.ANCHOR_ORDER` seats
    them apart and this function only moves ``rank`` WITHIN a source."""
    for source in B.DRIVER_ANCHOR_SOURCES:
        _rank_one_driver_source(bd, source)


def _rank_one_driver_source(bd: B.Board, source: str) -> None:
    """:func:`rank_driver_anchors` for ONE source. Separate so the two passes cannot share a variable
    and so an anchor set with no rows under this source leaves every other source untouched."""
    anchors = [a for a in bd.anchors if a.source == source]
    if not anchors:
        return
    key = rank_key_for(bd.rank_rule)
    pos = {}
    for a in anchors:
        # THE IDS THIS BOARD IS ANCHORED ON, not "the" driver: a resolved subject expands to its GROUP
        # (D4) and a group of two or more declares no single `driver_id`, so the rank is the BEST of
        # the group's own rows on this board. `subject_ids_on` is the one producer of that
        # intersection; a `focus_driver` anchor carries exactly one id and takes the same path.
        ids = list(bd.subject_ids_on(a.contract)) or (
            [bd.subject_driver] if bd.subject_driver else [])
        rows = [r for r in (bd.row(a.contract, i) for i in ids) if r is not None]
        # THE BOARD'S OWN TUPLE, not the shipped one by name: this ranking is "that driver's own state"
        # (Amendment 1), and under the alternative arm the driver's state is read by the alternative
        # tuple like every other rank consultation. The absent-row sentinel outranks nothing under
        # either tuple -- band 9 is past every coverage band there is.
        pos[a.contract] = min((key(r) for r in rows),
                              default=(9, 0.0, 0.0, 0.0, 0.0, 0.0, (ids[0] if ids else "")))
    if not pos:
        return
    # THE PRIOR (graph-declared) ORDER IS THE TIE-BREAK, and it is load-bearing rather than tidy: a
    # GLOBALLY-KEYED driver (`oni_climate`) is ONE StateRow shared by every board carrying it, so every
    # anchor's state is IDENTICAL by construction and the state rank cannot separate them. Without this
    # term the set would fall back to alphabetical order and DISCARD the confidence-and-lag order
    # `_driver_anchor_order` computed off the graph.
    prior = {a.contract: a.rank for a in anchors}
    ordered = sorted(pos, key=lambda c: (pos[c], prior.get(c, 0), c))
    seat = {c: i for i, c in enumerate(ordered)}
    # `replace`, NEVER A RE-CONSTRUCTION: a field-by-field rebuild silently DROPS any field added
    # after it was written, which is exactly what happened to `Anchor.named` -- the re-rank threw away
    # the record that the user had typed this market, so the anchor ceiling then cut it. One ranking
    # moves one field.
    new = [a if a.source != source else replace(a, rank=seat[a.contract]) for a in bd.anchors]
    # AND THE RE-SORT TAKES `ANCHOR_ORDER` TOO. It read the PRECEDENCE, so a board whose subject
    # anchors were re-ranked here would have been re-seated ahead of the market the question named --
    # undoing, one stage later, exactly what `resolve_anchors` had just ordered correctly.
    bd.anchors = tuple(sorted(new, key=B.anchor_order_key))


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


def fan_identity(bd: B.Board, graph, *, key_fn=None, turn_kind: str = "") -> None:
    """**"THE SAME READING" IS ONE SERIES** (CONTRACT K26, the 09-24 re-smoke's item 9, W's supply half).

    ``bd.fan`` names every far board of a shared driver ID, and the spillover line counted those as "the
    same reading declared on N other markets" -- MEASURED: palm/rape "thirteen other markets, the
    nearest being barley" was every card's OWN ending-stocks ratio (thirteen different series), soyoil
    "seven other markets" counted crush-margin boards on other crushes, and the deep turn's "thirty-four
    ... opposite on twenty-eight" compared a La_Nina-keyed row's edges at ONI +1.8 (the ENSO sign
    inverted for palm). Two facts are stamped, at ZERO reads:

      * every far row: ``far_key`` -- the far node's own series key from the walk's key plan
        (``key_fn``, the registry walk wave 1 prices with; the PRICED ``series_key`` where the wave
        already set one) -- and ``same_series``: that key equals the NEAR row's own series key. A far
        row with no ref, no plan or no near series is never the same reading.
      * every fan entry: ``pole_in_force`` -- where the entry's driver names one pole of a declared
        phase pair and the reading puts the OTHER pole in force (:func:`hop_phase`, the one phase
        producer), the pole in force's id: the near and far edges a reader is owed are THAT pole's
        (its own fan entry on the same board), never the pole the reading is not in. ``""`` otherwise.

    ``series_key`` keeps its HEAD meaning -- the key a wave PRICED -- because three consumers (the
    ``state_read`` marking below, the analog outcome leg and the spillover render) read it as "priced";
    the zero-read identity rides beside it under its own name. Nothing is read, priced or re-ranked."""
    key_fn = key_fn or _default_key_fn
    rows = {r.key: r for r in bd.rows}
    memo: dict = {}

    def _identity(f: dict) -> str:
        if f.get("series_key"):
            return str(f["series_key"])
        ref = str(f.get("ref") or "")
        if not ref or not f.get("contract"):
            return ""
        mk = (str(f["contract"]), str(f.get("driver_id") or ""), ref)
        if mk not in memo:
            far_d = _driver_of(graph, f["contract"], f.get("driver_id") or "")
            lbl = ""
            if far_d is not None:
                try:
                    plan = key_fn(ref, _WalkNode(f["contract"], far_d), turn_kind=turn_kind)
                    lbl = plan.key.label() if getattr(plan, "key", None) is not None else ""
                except Exception:                       # noqa: BLE001 -- an identity is never worth a turn
                    lbl = ""
            memo[mk] = lbl
        return memo[mk]

    for e in bd.fan:
        row = rows.get((e["contract"], e["driver_id"]))
        near = str(getattr(row, "series_key", "") or "") if row is not None else ""
        for f in e["far"]:
            k = _identity(f)
            f["far_key"] = k
            f["same_series"] = bool(k) and bool(near) and k == near
        pole = ""
        st = getattr(row, "state", None) if row is not None else None
        if st is not None and status_word(st.status) == "ok":
            ph = hop_phase(e["driver_id"], st)
            if _phase_reorients(ph):
                pole = str(ph.get("phase_in_force_driver") or "")
        e["pole_in_force"] = pole


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


def reading_side(pct, z, *, orient: int = 0) -> int:
    """WHICH TAIL OF ITS OWN RECORD A READING SITS IN -- ``+1`` the upper, ``-1`` the lower, ``0`` none
    (the 09-25 fix round, item W-2 / N4).

    ONE MEASURE, THE CHAIN'S OWN: the two signed components :func:`_hop_tail` takes the magnitude of --
    ``(pct - 50) / 50`` and ``z / 2.5``, each clipped to one -- and the side is the sign of the component
    that makes the reading loud (the larger magnitude). A reading where the two components tie with
    opposite signs, or where neither was measured, sits in no tail and returns ``0``.

    ``orient`` (+1 / -1) READS THE SIDE IN THE DRIVER'S OWN SENSE: ONI at the 93rd percentile is the
    upper tail of the warm pole's own reading and the LOWER tail of the cool pole's. 0 (every row that is
    not a pole member) is the series' own side, which is the driver's: a driver's series reads HIGH when
    there is MORE of the driver (the convention every chain agreement on this board already reads -- a
    dry-day-run z below zero is a SHORTER dry run). A pole member's condition on the BOARD is its phase,
    judged by the one phase producer (see :func:`row_side`), never by this function."""
    comps = []
    if pct is not None:
        comps.append(max(-1.0, min(1.0, (float(pct) - 50.0) / 50.0)))
    if z is not None:
        comps.append(max(-1.0, min(1.0, float(z) / 2.5)))
    if not comps:
        return 0
    top = max(abs(c) for c in comps)
    signs = {(1 if c > 0 else -1) for c in comps if abs(c) == top and c != 0.0}
    if len(signs) != 1:
        return 0
    side = signs.pop()
    o = int(orient or 0)
    return side * o if o else side


def row_side(row) -> Optional[int]:
    """WHICH TAIL OF ITS OWN RECORD ONE BOARD ROW'S SERVED READING SITS IN, AS A CONDITION OF A PATTERN
    -- ``+1`` more of the driver, ``-1`` less, ``0`` no tail -- or ``None`` where the condition's state is
    NOT a reading's tail (the 09-25 fix round, W-2). ``None`` keeps HEAD's reading of the condition, and
    it has exactly three declared causes, each read off the graph or the row, never off a name:

    * NO SERVED READING (no state, or a status other than ``ok``): there is no tail to read.
    * A MEMBER OF A DECLARED PHASE PAIR (:func:`hop_phase`'s ``phase_driver``, the one phase producer): its
      condition is the PHASE, and the render's quorum fold already judges it on the page off the same
      producer -- a member read in the phase opposite the one in force is stated by name and left out of
      the count (``render._series_fold``'s ``phase_opposed``, review round 2 MAJOR 10). Deciding it a second
      time here would move the member out of the list that fold reads and silence the sentence that states
      it (MEASURED on the b40 fixture: "El Nino names the phase opposite the one in force on that reading,
      so it is not counted here" left the supply-squeeze row).
    * A NODE OF A REGIME TYPE (:data:`REGIME_NODE_TYPES`, the DAG's declared ``policy_event`` type): its state
      is its DATED ACTION -- the walk reads it that way everywhere else (:func:`hop_event`'s regime ladder,
      which reads the SAME declared set) -- and the trade-flow series bound to it measures the policy's
      EFFECT under a polarity the graph does not declare (``export_ban`` on an export level,
      ``import_tariff`` on an import level: HIGH exports are NO ban). A tail of that series is not the
      condition's side. MEASURED: on the b40 fixture the Indonesian export ban read on a low export level
      would otherwise have been counted AGAINST the policy-shock spike.

    Every other row: :func:`reading_side` of its percentile and z -- the figures the loud set ranked it by."""
    st = getattr(row, "state", None)
    if st is None or status_word(getattr(st, "status", "") or "") != "ok":
        return None
    # ONE DECLARED SET, READ IN BOTH PLACES (the 09-25 close-out, RW-3 / VERIFY MINOR-7): the regime ladder
    # and this side test read :data:`REGIME_NODE_TYPES` -- never a second literal copy of the type word.
    if str(getattr(row, "type", "") or "") in REGIME_NODE_TYPES:
        return None
    if hop_phase(getattr(row, "driver_id", ""), st).get("phase_driver"):
        return None
    return reading_side(_measure_value(getattr(st, "percentile", None)),
                        _measure_value(getattr(st, "z", None)))


def convergence_rows(graph, contract: str, loud_ids, *, loud_k: int, band_ids=(),
                     measured_ids=None, sides=None) -> list:
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
    id is then reported as it was before.

    **A CONDITION COUNTS ONLY IN THE TAIL THE PATTERN'S CARD DECLARES FOR IT** (the 09-25 fix round, item
    W-2 / N4, the cocoa FATAL). ``sides`` is ``{driver_id: +1 / -1 / 0}`` -- :func:`row_side` of every
    loud row on this board whose condition is a reading's tail (a phase-pair member and a policy_event node
    are not: see :func:`row_side`; absent from ``sides``, they keep HEAD's reading). The tail a pattern asks of each of its drivers
    is the CARD's own: the pattern's declared ``direction`` times the driver's declared ``sign`` (``+``
    x ``+`` asks for the upper tail -- more of the driver pushes the price the pattern's way; ``+`` x
    ``-`` asks for the lower). A loud reading in THAT tail is a condition showing (``matched``); a loud
    reading in the OTHER tail counts AGAINST the pattern (``against``, stated, never dropped); a loud
    reading whose side cannot be placed against the card -- the driver declares ``0`` (no committed
    direction) or the reading sits in no tail -- is ``unsided`` and is not counted either. A loud row
    with NO served reading (a text-tier rank-cut row, an open event) has no tail to read and keeps HEAD's
    reading (``matched_unmeasured``), and so does every loud row absent from ``sides`` or mapped to ``None``. MEASURED on the 09-25 cocoa page: "three of its six conditions
    are counted" for the West African deficit squeeze was a WET dry-day run (-1.49 sigma, 3rd percentile)
    and a COOL max-temperature anomaly (6th percentile) -- both drivers declared ``+`` in a ``+``
    pattern -- plus the unread export-pace lag. ``None`` (every caller that does not pass it) is HEAD,
    byte for byte, and adds no key. The rejected lexical form: pattern-name or driver-name keyword
    rules."""
    loud, banded = set(loud_ids), set(band_ids)
    measured = None if measured_ids is None else set(measured_ids)
    side_of = None if sides is None else dict(sides)
    out = []
    contract_obj = (getattr(graph, "contracts", {}) or {}).get(contract)
    declared = {str(getattr(d, "id", "") or ""): str(getattr(d, "sign", "") or "")
                for d in (getattr(contract_obj, "drivers", ()) or ())}
    for s in (getattr(contract_obj, "convergence", ()) or ()):
        loud_members = [d for d in s.drivers if d in loud]
        against: list = []
        unsided: list = []
        if side_of is None:
            matched = loud_members
        else:
            matched = []
            pole = _SIGN_INT.get(str(getattr(s, "direction", "") or ""))
            for d in loud_members:
                if side_of.get(d) is None:
                    matched.append(d)              # no reading's tail to read (row_side): HEAD
                    continue
                want = _SIGN_INT.get(declared.get(d, ""))
                need = (pole * want) if (pole is not None and want is not None) else 0
                got = int(side_of.get(d) or 0)
                if not need or not got:
                    unsided.append(d)
                elif got == need:
                    matched.append(d)
                else:
                    against.append(d)
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
        if side_of is not None:
            # THE TAIL VERDICTS, APPENDED AT THE ROW'S TAIL (W-2): the drivers read loud in the tail
            # opposite the one the card asks of them, and the loud readings the card cannot place.
            # Each interaction carries its own opposite-tail members beside HEAD's rank-based
            # ``rendered`` (the co-occurrence rank claim stays true; which side it sits on is stated).
            out[-1]["against"] = tuple(against)
            out[-1]["unsided"] = tuple(unsided)
            out[-1]["interactions"] = tuple(
                dict(i, against=tuple(d for d in i["when"] if d in against)) for i in inter)
    out.sort(key=lambda r: (-r["n_matched"], r["name"]))
    return out


def complex_pairs(pairs, on_board) -> list:
    """The 35 declared pairs (`complex_map.yaml`) that render: BOTH sides on the board (sec 3.5).

    A pair is VOCABULARY, never a decision. Its RV rows (World su_ratio per side, the price standing)
    enter as EVIDENCE rows UNDER the pair and never as the thing that decided it -- RV / regional legs
    are rows, never relevance gates."""
    have = set(on_board)
    return [{"pair": tuple(p), "rendered": set(p) <= have} for p in (pairs or ())]


def chain_paths(chains, on_board, *, loud_boards=(), on_nodes=(), loud_nodes=()) -> list:
    """`chain_map.yaml` (10) and `transmission_map.yaml` (2) as DECLARED PATHS, ordered by the number of
    LOUD hops then hops on the board then FILE ORDER (sec 3.5). Selection by file order ALONE retires
    in phase 4.

    ``loud_hops`` AND ``hops_on_board`` ARE TWO COUNTS AND THE FIRST BUILD HAD ONLY ONE. It called
    "hops on the board" `loud_hops`, so a chain every one of whose boards was touched and none of whose
    boards carried a loud row out-ranked a chain with one genuinely loud hop -- sec 3.5's ordering word
    measuring presence instead of loudness. ``loud_boards`` is the set of boards carrying at least one
    row in the loud set; empty (the default) means the caller is asking the presence question only, and
    every ``loud_hops`` is then 0 and the file order decides, which is the honest degenerate case.

    ``on_nodes`` / ``loud_nodes`` ARE THE SECOND AXIS, and without them this function could not read
    the estate's own curated file. :func:`chain_row_shape` says which axis a row is on; a row whose
    hops are DRIVER NODES is counted against the driver ids on the board, a row whose hops are MARKETS
    against the board slugs, and the axis is DECLARED per row rather than assumed for the file.

    **THE NODE AXIS IS A SET OF ``(contract, driver_id)`` PAIRS AND NEVER A FLAT ID SET (E11, review
    round 2 M3).** The first cut passed ``{r.driver_id for r in bd.rows}`` -- one flat set over a board
    that spans contracts -- and guarded it with "is ANY of this row's contracts on the board", which is
    not the same question. MEASURED on the corn+wheat board (one of the five smoke turns): a curated
    CORN chain whose hops are ``area`` and ``ending_stocks`` counted TWO LOUD HOPS and rendered off
    WHEAT's two rows, because both boards declare both ids. One board's readings were ordering another
    board's curated chain -- the string-identity join this estate has a standing memory about, arrived
    at through a config instead of through a rename. The count is now per contract: a hop is on the
    board when THE ROW'S OWN DECLARED CONTRACT carries it."""
    have_b, loud_b = set(on_board), set(loud_boards)
    have_n = {(str(c), str(d)) for c, d in (on_nodes or ())}
    loud_n = {(str(c), str(d)) for c, d in (loud_nodes or ())}
    out = []
    for i, ch in enumerate(chains or ()):
        axis, hops, cid = chain_row_shape(ch, i)
        if axis == "node":
            # THE ROW'S OWN CONTRACTS, INTERSECTED WITH THE BOARD. A curated row that declares none
            # (the degenerate case) is read against every contract the board carries, which is what
            # the flat set used to do for EVERY row and is honest only where nothing was declared.
            declared = tuple(str(c) for c in (ch.get("contracts") or ())
                             if isinstance(ch, dict) and str(c or ""))
            scope = ([c for c in declared if c in have_b] if declared
                     else sorted({c for c, _d in have_n}))
            on_n = sum(1 for h in hops if any((c, h) in have_n for c in scope))
            loud_h = sum(1 for h in hops if any((c, h) in loud_n for c in scope))
            rendered = bool(hops) and bool(scope) and on_n == len(hops)
        else:
            on_n = sum(1 for h in hops if h in have_b)
            loud_h = sum(1 for h in hops if h in loud_b)
            rendered = bool(hops) and on_n == len(hops)
        out.append({"name": cid or f"chain_{i}", "hops": hops, "axis": axis,
                    "loud_hops": loud_h, "hops_on_board": on_n, "file_order": i,
                    "rendered": rendered})
    out.sort(key=lambda c: (-c["loud_hops"], -c["hops_on_board"], c["file_order"]))
    return out


def chain_row_shape(ch, i: int = 0) -> tuple:
    """``(axis, hops, id)`` for ONE curated row of either shipped map, or of a plain hop list.

    **THE THREE SHAPES DISAGREE ON TWO AXES AND THE FIRST BUILD READ ONLY ONE OF THEM.**
    ``cascade.load_chain_map()`` rows are ``{id, contracts:[slug], hops:[{node, ref, country?}]}`` --
    DRIVER NODES. ``cascade.load_transmission_map()`` rows are ``{id, links:[{pair_id, source,
    target, nature}]}`` -- MARKET to MARKET. :func:`chain_paths` read ``ch['name']`` (the rows carry
    ``id``) and then ``h in loud`` with ``h`` a dict -- ``TypeError: unhashable type: 'dict'`` on the
    FIRST row of the first map, which is why the ten curated chains have reached no turn:
    ``notes[kind=chains].rows == ()`` on 5 of 5 banked payloads, and the seam has always passed
    ``chains=()`` so the raise has never been reached either.

    ``'board'`` is the plain-string shape the S2 landing assumed and the fixtures still use, kept so
    the ``chains=()`` call and every hand-built row behave exactly as they did."""
    if not isinstance(ch, dict):
        return ("board", (), "")
    cid = str(ch.get("id") or ch.get("name") or "")
    raw = ch.get("hops")
    if raw:
        if any(isinstance(h, dict) for h in raw):
            return ("node", tuple(str((h or {}).get("node") or "") for h in raw if
                                  str((h or {}).get("node") or "")), cid)
        return ("board", tuple(str(h) for h in raw), cid)
    links = ch.get("links") or ()
    if links:
        seq: list = []
        for lk in links:
            src, tgt = str((lk or {}).get("source") or ""), str((lk or {}).get("target") or "")
            if src and not seq:
                seq.append(src)
            if tgt:
                seq.append(tgt)
        return ("market", tuple(seq), cid)
    return ("board", (), cid)


# ---------------------------------------------------------------------------------------------------
# 3.5b THE COMPOSED CHAIN (S8 DESIGN B.0-B.3, owner doctrine 2026-09-17)
#
# THE ONE SENTENCE THIS SECTION IS. `ancestor_paths` is INTRA-DAG by construction (`rows_by_id` is
# `bd.rows_for(contract)`, :784) and `cross_edges` is INTER-CONTRACT only (:858); nothing in the
# package composed the two, so the engine could say "crude sits two hops upstream of the bean price"
# and, separately, "the same reading is declared on twenty-three other markets", and never the one
# sentence a PM buys -- crude at +0.51 z -> the declared edge into crush margin -> crush at the 92nd
# percentile -> the declared crushed_into edge -> soybean meal. A CHAIN is that composition, ranked in
# 100 PRINTABLE points, receipted at the hop the action acts on, graded by what the hops' own numbers
# did the last times this reading fired, and NEVER gated.
#
# NO GATE ANYWHERE. The only exclusions in this whole section are POINT-IN-TIME (a receipt dated after
# the as-of; a firing whose declared window has not closed) and EXISTENCE (a hop with no series prints
# its declared direction alone). The history stat is a WEIGHT and a printed number with its sample
# size; a chain with ONE past firing and a first-percentile receipt hop ranks and renders, and
# `test_state_walk` pins exactly that. Frequency floors deny the tail.
#
# EVERY BYTE OF THIS SECTION IS DARK UNTIL A CALLER PASSES `state_chain=True`. :func:`_stage2` builds
# no chain, stamps no chain reason and swaps no render cap without it, so a board-on / chain-off turn
# is byte-identical to the 2026-09-16 smoke and a flag-off turn is byte-identical to HEAD.
# ---------------------------------------------------------------------------------------------------
#: The seven rank terms of DESIGN B.2 and their ceilings. 100 points, each one printable in words, so
#: the selection is falsifiable on the page rather than asserted.
CHAIN_TERMS: tuple[str, ...] = ("tail", "reach", "event", "history", "asymmetry", "confidence", "lag")
CHAIN_TERM_MAX: dict = {"tail": 25.0, "reach": 25.0, "event": 20.0, "history": 15.0,
                        "asymmetry": 10.0, "confidence": 3.0, "lag": 2.0}

#: HISTORY's NEUTRAL score -- what an unknown or thin record is worth. It is half of the term and not
#: zero, because a chain nobody has a record for must not be ranked below a chain with a BAD record
#: (ruling R2: the stat grades, it never gates). The block prints "history thin: <n> firings" beside it.
CHAIN_HISTORY_NEUTRAL: float = 7.5
#: Below this many past firings the history term is NEUTRAL and the words say so.
CHAIN_HISTORY_THIN_N: int = 3
#: At or above this many the term takes its full weight; between the two it is discounted by 0.7.
CHAIN_HISTORY_FULL_N: int = 6
CHAIN_HISTORY_DISCOUNT: float = 0.7

#: EVENT's ladder (DESIGN B.2 / B.4's order of choice). An ENACTED action inside the hop's own window
#: is worth the most a receipt can be worth here; a report sentence about the mechanism is worth a
#: third of it; nothing is worth nothing and the chain SAYS SO rather than going quiet.
CHAIN_EVENT_POINTS: dict = {"open": 20, "closed": 12, "mechanism": 6, "none": 0}

#: **WHAT A HOP'S DATED DOCUMENT IS, IN ONE CLOSED VOCABULARY** (CONTRACT C7, the 09-23 re-smoke's
#: event ledger: a conditional forecast scored 20 of 20 as an OPEN ACTION on cotton, and a standing
#: tariff scored 0 of 20 as a SPENT impulse on the tariff turn). The four words of
#: :data:`CHAIN_EVENT_POINTS` price a receipt; these eight say what the document IS, and the two are
#: kept apart so the points table -- and every banked score -- keeps HEAD's four words:
#:
#:   ``action_open`` / ``action_closed`` / ``action_aged`` -- a dated ACTION, its declared lag window
#:       still running, shut within one band-length of the as-of, or shut before that (HEAD's three);
#:   ``guidance`` -- a dated FORECAST: the event's own interval, built from ``event_date`` AT ITS
#:       PRECISION, STARTS after the document's own date (``contracts.py``'s ``event_date >
#:       document_date marks forward guidance``) -- the whole event lies in the document's future.
#:       (09-23 fix round, review WT F-1: the first cut read "the interval ENDS after the document" and so
#:       filed every month-, quarter- or year-precision event REPORTED INSIDE ITS OWN PERIOD as a
#:       forecast -- "La Nina switched to neutral in March 2023", published 30 March 2023, printed "a dated
#:       forecast ... not an action".) An interval that STRADDLES its document date -- the report written
#:       inside the period it is about ("during 2026" published 2026-04-03) -- is ``report_in_reach`` (or
#:       ``report_outside``): a dated report, scored at the mechanism weight and never worded as a
#:       forecast or as "not an action". Whether such a report states a realised or a conditional event is
#:       an EXTRACTION fact (a modality on the proposition) -- docketed, never read off its words;
#:   ``regime_in_force`` -- a dated action on a node the graph types as a REGIME (owner decision 3):
#:       the newest such action is read as in force until a later dated action on the same node;
#:   ``report_in_reach`` / ``report_outside`` -- a dated REPORT: a sentence with a publication date and
#:       no event date (HEAD's choice (3) and its refusal), or a hop's dated event whose interval straddles
#:       its own document date -- inside / outside one band-length;
#:   ``none`` -- nothing dated reached this turn.
#:
#: A HOP carries a dated-event word (the first five, or ``none``), or ``report_outside`` for a forecast
#: whose whole interval closed more than one band-length before the as-of (a spent report, never
#: guidance); ``report_in_reach`` is the CHAIN's alone, chosen at DESIGN B.4's third choice over the
#: hops' report sentences, and the chain's ``report_outside`` names the sentence that choice refused.
EVENT_KINDS: tuple[str, ...] = ("action_open", "action_closed", "action_aged", "guidance",
                                "regime_in_force", "report_in_reach", "report_outside", "none")

#: OWNER DECISION 3's knob, at its build default: a regime in force is scored at the CLOSED weight
#: (12 of 20), not the OPEN one, until the evidence carries a polarity. One name, so the decision is
#: one edit.
REGIME_RECEIPT_KIND: str = "closed"

#: EVENT KIND -> the POINTS word it scores under (CONTRACT C7's mapping, verbatim). ``Chain.receipt_kind``
#: stays one of HEAD's four words, so :data:`CHAIN_EVENT_POINTS` is never touched.
EVENT_KIND_RECEIPT: dict = {"action_open": "open", "action_closed": "closed", "action_aged": "none",
                            "guidance": "mechanism", "regime_in_force": REGIME_RECEIPT_KIND,
                            "report_in_reach": "mechanism", "report_outside": "none",
                            "none": "none"}

#: THE NODE TYPE WHOSE DATED ACTIONS ARE REGIMES (owner decision 3). It is the causal schema's OWN
#: declared type vocabulary (``causal/schema.py:38``, ``causal/author._DRIVER_TYPES``), read off the
#: node's ``type`` field -- never a list of ids and never a word in the document's text.
REGIME_NODE_TYPES: frozenset = frozenset({"policy_event"})

#: The ORDER a non-regime hop's dated documents are chosen in: DESIGN B.4's own ladder (an enacted
#: action inside its window, then a recently closed one, then a forecast at the mechanism tier), and
#: an aged action last -- chosen only so it is COUNTED, never scored.
_EVENT_CHOICE_ORDER: tuple[str, ...] = ("action_open", "action_closed", "report_in_reach", "guidance",
                                        "action_aged", "report_outside")

#: The AGREEMENT word a hop prints, from `stats.sign_agreement`'s three-valued verdict. The estate
#: already computes this on the cascade leg (`cw_verdicts`), so the chain leg reuses the ONE
#: calculator rather than minting a second one.
CHAIN_AGREEMENT_WORDS: dict = {"aligned": "agree", "at_odds": "run against",
                               "undetermined": "do not settle"}

#: What makes a row a BUFFER for the ASYMMETRY term -- a stock, a ratio, a margin or a pace, i.e. the
#: quantities whose tails are convex rather than merely extreme. Substring match on the driver id.
#: IT IS THE FALLBACK AND NO LONGER THE RULE (owner ruling 6b, 2026-09-18): the family is resolved PER
#: ANCHOR from the card registry by :func:`anchor_buffer_ids`, and this literal list answers only where
#: no board was threaded (the offline ranking harness), which is a degenerate case rather than a market.
CHAIN_BUFFER_TOKENS: tuple[str, ...] = ("su_ratio", "ending_stock", "stocks", "crush_margin",
                                        "board_crush", "export_pace")

#: A COT percentile at or past these cuts is a CROWDED position (owner ruling 1, 2026-09-18), read on
#: the same 90/10 cuts the ASYMMETRY term already reads for a buffer -- one extremity rule, two rows.
CHAIN_CROWDED_HIGH: float = 90.0
CHAIN_CROWDED_LOW: float = 10.0
#: What a crowded position the chain's OWN way is worth, inside the ten ASYMMETRY points.
CHAIN_POSITIONING_POINTS: float = 5.0

#: WHICH SLOT A RENDERED CHAIN TOOK ITS SEAT IN -- a closed word, published so a reader of the trace
#: and a reader of the page cannot spell it two ways (owner ruling 2026-09-22, the render slots).
#:
#: ``top`` is the rank's own top K, ``sign`` the sign-diversity swap, and the three that follow are the
#: seats THE QUESTION anchors: the SUBJECT the turn is anchored on, the PAIR call a multi-market
#: question demands, and the HORIZON the question asked about. A slot NEVER moves the rank and never
#: removes a chain; it only reserves a seat for a chain the rank would otherwise have left below the
#: cap, and it adds no row at all where the top K already carries one that qualifies.
CHAIN_SLOTS: tuple[str, ...] = ("top", "sign", "subject", "pair", "horizon")

#: **WHAT HAPPENED TO EACH OF THE THREE QUESTION SLOTS** (CONTRACT C7, defect D9). The five ``slot_*``
#: counts count only the seats a slot TOOK, so four different facts printed one number -- the 09-23
#: re-smoke read ``slot_subject 0`` on ten of ten turns as "never lit" when the subject resolver had
#: never run. One closed word per slot, stamped inside the SAME branches of
#: :func:`chain_render_set` that decide the seat:
#:
#:   ``not_asked``        -- the question anchors nothing for this slot (one named market, no horizon,
#:                           or a resolver that ran and picked nothing);
#:   ``resolver_off``     -- the SUBJECT slot only: the resolver payload never ran on this turn
#:                           (``Board.subject`` is empty -- the seam writes it only when it is on);
#:   ``answered_by_rank`` -- a chain already on the page when the slot is asked answers it: the top K,
#:                           the sign swap, or an earlier slot's seat (the selection's own test,
#:                           ``any(test(c) for c in picked)``, and it seats nothing);
#:   ``seated``           -- the slot took a seat for a chain the rank left below the cap;
#:   ``no_candidate``     -- the slot was asked and no chain in the pool answers it.
SLOT_STATES: tuple[str, ...] = ("not_asked", "resolver_off", "answered_by_rank", "seated",
                                "no_candidate")

#: The three QUESTION slots, in :func:`chain_render_set`'s own seat order.
QUESTION_SLOTS: tuple[str, ...] = ("subject", "pair", "horizon")

#: How many chains may render IN FULL beyond ``chain_render_k``. The slots can seat at most three
#: extra chains; the block's own budget cannot absorb three extra full chain rows, so the bound is
#: ``K + 2`` and a slot chain past it renders as ONE LINE -- never dropped, and counted
#: (``chain_counts["rendered_one_line"]``).
CHAIN_SLOT_FULL_OVER_K: int = 2

#: **THE W -> R SEAM, IN ONE SPELLING (E11).** Every field the RENDER consumes off this module's own
#: objects, named here once, so a consumer never has to guess and a pin can assert the name against
#: the SHIPPED type rather than against a stand-in that carries whatever the reader hoped for.
#:
#: THIS CONSTANT EXISTS BECAUSE FOUR OWNER-ORDERED SURFACES RENDERED NOTHING (the round-2 census's
#: blocker 2, measured): ``render.chain_state_words`` read ``tail_peak_month`` and ``lag_window_end``
#: where the walk carries ``tail_peak_date`` and ``tail_lag_to``; ``render.chain_arithmetic_words``
#: read ``Chain.data_scope`` where the walk carries ``Chain.scope``; ``render.sb_chain_count`` read
#: ``chain_counts["cross_event"]`` where the walk carries ``chain_counts["cross_market_event"]``. On
#: the page: ``"peaked"`` 0 times against 6 of 6 rendered chains whose TAIL term was SCORED on a
#: window peak, and a hop printed at the 28th percentile scored at the 94th. Every pin on both sides
#: was GREEN, because every pin asserted against a ``types.SimpleNamespace`` stand-in. This is the
#: string-identity failure class this estate has a standing memory about, arrived at through a handoff
#: instead of a rename -- so the names now live in ONE place and a test resolves every one of them
#: against a real :class:`Chain` / :class:`ChainHop` / :func:`chain_counts` built from the fixture.
#:
#: THE NAMES ARE DOTTED AND THE FIRST SEGMENT IS THE OWNER: ``ChainHop.x``, ``Chain.x``,
#: ``Chain.<dict>.<key>`` for the three dicts a chain carries, ``chain_counts.<key>``. A consumer
#: reads THESE; a consumer that reads anything else is reading a name this module does not publish.
#:
#: WHAT IS DELIBERATELY ABSENT: ``Chain.outcome``'s ``table`` / ``metric`` / ``country``. Those are
#: declared by the BASIS the outcome was computed on (lane C's ``spread_fn`` names its own card) and
#: the render owns the default; a walk that published them would be publishing a card it did not read.
CHAIN_SEAM_FIELDS: tuple[str, ...] = (
    # ── the hop ────────────────────────────────────────────────────────────────────────────────────
    "ChainHop.contract", "ChainHop.driver_id", "ChainHop.key", "ChainHop.measured",
    # THE SERIES KEY IS A CONSUMED SEAM FIELD (lane R's round-3 handoff R3-W2): `seam._dim_for_hop`
    # matches a chain hop to the analog leg's declared dimension on it, and it is also this module's
    # own diversity fold (`ChainHop.fold_key`). One reading, one key, one spelling.
    "ChainHop.series_key",
    "ChainHop.percentile", "ChainHop.z", "ChainHop.level_shown", "ChainHop.unit",
    "ChainHop.narrate_unit", "ChainHop.run_direction", "ChainHop.run_length", "ChainHop.run_since",
    "ChainHop.level_date", "ChainHop.knowledge_date", "ChainHop.convention_label",
    "ChainHop.sign", "ChainHop.lag", "ChainHop.lag_band", "ChainHop.confidence",
    "ChainHop.mechanism", "ChainHop.silver_status", "ChainHop.event_date", "ChainHop.event_open",
    "ChainHop.event_receipt", "ChainHop.receipts_top", "ChainHop.tail",
    # the declared lag window's own loudest reading (owner ruling 5). `tail_peak_percentile` is the
    # PERCENTILE the page prints and `tail_peak` is the MEASURE the rank scored -- two facts, two
    # names, and the round-2 census found the render already reading the percentile one correctly.
    "ChainHop.tail_peak", "ChainHop.tail_peak_percentile", "ChainHop.tail_peak_date",
    "ChainHop.tail_window_from", "ChainHop.tail_lag_to", "ChainHop.chain_tail",
    # THE 09-23 FIX ROUND (CONTRACT C7 / C8, lane W). What the hop's dated document IS (one of
    # `EVENT_KINDS`) and the interval its date covers AT ITS PRECISION; the precision it was dated at;
    # the declared phase pair this hop belongs to and which pole of it is in force (read off
    # `render.phase_for_state`, never re-derived); the pole this hop names (+1 / -1, 0 when it names
    # none) and whether its tail was scored on that pole; and where the effect of its NEWEST reading
    # closes (`effect_window`'s `closes`, beside `tail_lag_to` = its `peak_closes`).
    "ChainHop.event_kind", "ChainHop.event_interval", "ChainHop.event_precision",
    "ChainHop.driver_type",
    "ChainHop.phase_driver", "ChainHop.phase_in_force", "ChainHop.phase_in_force_driver",
    "ChainHop.phase_orient", "ChainHop.phase_reoriented", "ChainHop.effect_closes",
    # ── the chain ──────────────────────────────────────────────────────────────────────────────────
    "Chain.contract", "Chain.asof", "Chain.hops", "Chain.hop_ids", "Chain.agreements",
    "Chain.edge_signs", "Chain.cross", "Chain.terminal", "Chain.terminal_key",
    "Chain.terminal_level", "Chain.terminal_unit", "Chain.terminal_percentile", "Chain.depth",
    "Chain.score", "Chain.terms", "Chain.notes", "Chain.scope", "Chain.positioning",
    "Chain.receipt_index", "Chain.receipt_hop", "Chain.receipt", "Chain.receipt_kind",
    # `Chain.receipts_aged_out` is the PER-CHAIN document count and `chain_counts.receipts_aged_out`
    # is the POOL's DISTINCT one -- two arithmetics over one population, each under its own owner's
    # name (round-4 census 3). `aged_receipt_hop` / `aged_receipt_date` are WHICH document that was
    # and WHERE it sits, so a row naming it names the hop the producer declared it against (census 4).
    "Chain.receipt_words", "Chain.receipts_aged_out", "Chain.aged_receipt_hop",
    "Chain.aged_receipt_date",
    # A REPORT SENTENCE THE MECHANISM BOUND REFUSED: its own two names, its own noun (round-5 blocker 1/4).
    "Chain.mechanism_refused_hop", "Chain.mechanism_refused_date", "Chain.history", "Chain.outcome",
    "Chain.unnamed_terminal", "Chain.declared_sign", "Chain.direction", "Chain.side",
    "Chain.against_hops", "Chain.curated", "Chain.rendered", "Chain.full", "Chain.slot",
    "Chain.decline",
    # THE CHAIN'S OWN EVENT WORD (CONTRACT C7): the `EVENT_KINDS` member of the document it was
    # receipted on, BESIDE `receipt_kind` (HEAD's four points words, unchanged). And WHICH live
    # question slots this chain answers -- the trace payload carries each live slot's best candidate.
    "Chain.event_kind", "Chain.slot_fits",
    # ── the three dicts a chain carries ────────────────────────────────────────────────────────────
    # `terms_scored` is the count the PAGE prints (every term with points above zero) and
    # `terms_read` is how many of the seven had anything to READ (review MA-3). Two facts, two
    # names, one arithmetic each -- never one word over two numbers (lane R's handoff R3-W1).
    "Chain.scope.terms_total", "Chain.scope.terms_scored", "Chain.scope.terms_read",
    "Chain.scope.hops",
    "Chain.scope.hops_no_series", "Chain.scope.buffer_series", "Chain.scope.events_in_corpus",
    "Chain.scope.price_read", "Chain.scope.price_standing",
    "Chain.positioning.percentile", "Chain.positioning.against", "Chain.positioning.key",
    "Chain.outcome.n", "Chain.outcome.n_in", "Chain.outcome.median_move", "Chain.outcome.low",
    "Chain.outcome.high", "Chain.outcome.share_declared_way", "Chain.outcome.unit",
    "Chain.outcome.scope", "Chain.outcome.window_from", "Chain.outcome.window_to",
    "Chain.outcome.words",
    # THE RECORD'S OWN UNCOUNTED HALF. `unmeasured` is a PRINTED figure ("on any of the fourteen past
    # firings of this reading") and every firing the producer found is in it or in `n_firings`.
    "Chain.history.unmeasured",
    # ── the count line ─────────────────────────────────────────────────────────────────────────────
    "chain_counts.total", "chain_counts.rendered", "chain_counts.rendered_one_line",
    "chain_counts.distinct_sequences", "chain_counts.distinct_markets",
    "chain_counts.distinct_unnamed_markets", "chain_counts.below_print_line",
    "chain_counts.render_cap", "chain_counts.no_measured_hop",
    "chain_counts.cross_market_event", "chain_counts.cross_market_event_rendered",
    # THE DISTINCT DOCUMENTS, over the pool. The per-chain count lives on `Chain.receipts_aged_out`
    # above; this name is the count line's, and it counts each dated action ONCE however many chains
    # walk the row it sits on (round-4 census 3).
    "chain_counts.receipts_aged_out", "chain_counts.mechanism_refused", "chain_counts.state_two_hops",
    "chain_counts.with_event",
    "chain_counts.with_document", "chain_counts.reaching_unnamed", "chain_counts.cross_earned",
    "chain_counts.curated", "chain_counts.for_side", "chain_counts.against_side",
    "chain_counts.history_n", "chain_counts.slot_top", "chain_counts.slot_sign",
    "chain_counts.slot_subject", "chain_counts.slot_pair", "chain_counts.slot_horizon",
    # THE THREE KEYS THE DICT CARRIES THAT THE SELECTION DOES NOT MINT, declared here because a key
    # that reaches `Board.trace()` and the census record with no published spelling is the shape the
    # round-2 census caught on `cross_event` (round-3 census, section 9). `cross_unpriced` and
    # `single_hop_paths` are stamped by the BUILDER (:func:`chain_rows`) -- the two facts it knows and
    # the selection cannot -- and `disagreement` is :func:`chain_disagreement_words`' one sentence,
    # stamped onto the same dict by :func:`stage2` so the trace carries the count line WITH the line
    # that says where the carried chains disagree.
    "chain_counts.cross_unpriced", "chain_counts.single_hop_paths", "chain_counts.disagreement",
    # ONE CLOSED `SLOT_STATES` WORD PER QUESTION SLOT (CONTRACT C7, D9) -- `{subject, pair, horizon}`,
    # stamped by the branches that decided the seat; the five `slot_*` counts above are unchanged.
    "chain_counts.slot_state",
    # ── THE 09-24 FIX ROUND (CONTRACT K9 / K10 / K12 / K13 / K21, lane W) ─────────────────────────────
    # The node ids folded into one link (K12); a premise not in force (K13); the terminal reading the
    # last link's verdict read (K10); the lexical tier of the subject pick a chain carries (K9, O-5);
    # the one rendered chain that answers the asked horizon (K21). And the count line's three new keys:
    # how many PATHS walked one series twice and were folded, how many pool chains carry a premise not
    # in force, and the rank index (among the rendered chains, rank order) of the horizon's chain.
    "ChainHop.aliases",
    "Chain.premise_off", "Chain.terminal_reading", "Chain.subject_tier", "Chain.answers_horizon",
    "chain_counts.series_folded", "chain_counts.premise_off", "chain_counts.horizon_chain",
)

_SIGN_INT: dict = {"+": 1, "-": -1}


@dataclass(frozen=True)
class AnchorFacts:
    """WHAT THE BOARD KNOWS ABOUT THE ANCHOR ITSELF, resolved ONCE per contract and read by every
    candidate chain on it (owner rulings 1, 2 and 6, 2026-09-18).

    **EACH ANCHOR IS JUDGED ON THE DATA IT HAS.** The rank is relative WITHIN one board, so a data-poor
    anchor still gets its best chains -- and what makes that honest rather than silent is that the
    absences are FACTS ON THE OBJECT: which buffer family this market actually serves, whether it
    serves one at all, whether any dated document reached the turn, and what the price row carries.
    A term that scores zero because the market has no such series says so in its own sentence.

    It is ABSENT (``None``) on the offline ranking harness, which threads no board; every consumer
    then falls back to the shipped behaviour and says which fallback it took."""

    contract: str = ""
    # -- the ASYMMETRY term's BUFFER family, resolved from the card registry (ruling 6b) -------------
    buffer_ids: frozenset = frozenset()
    buffer_served: bool = False
    # -- POSITIONING (ruling 1) ----------------------------------------------------------------------
    positioning_id: str = ""
    positioning_percentile: Optional[float] = None
    # -- the anchor's own PRICE row (ruling 2) -------------------------------------------------------
    price_tail: float = 0.0
    price_percentile: Optional[float] = None
    price_window: str = ""
    # -- the data scope the arithmetic line states (ruling 6a) ---------------------------------------
    events_served: bool = True


@dataclass(frozen=True)
class ChainHop:
    """ONE hop of a composed chain: the DAG's declaration plus what the board read for it.

    IT IS FROZEN AND MEMOISED PER ``(contract, driver_id)``. A driver's facts do not depend on which
    chain walks through it, and a board that builds five hundred candidate chains over forty rows must
    not build five hundred copies of the same reading. What DOES depend on the chain is the AGREEMENT
    between this hop and the next one, so that rides on :class:`Chain` as a parallel tuple and never
    here -- one hop, many successors.

    THE JOIN KEY IS ``(contract, driver_id)`` AND THE SERIES KEY, NEVER THE DRIVER ID ALONE (E11).
    ``area`` is a driver of ``corn_cbot`` AND of ``soft_red_winter_wheat_cbot`` and the two read the
    98th and the 1st percentile on the same turn; ``render.series_by_driver`` keys on the bare id with
    ``setdefault`` and returns ONE reading per id for the whole board, and a chain built off it would
    print one board's tail on the other board's chain. Measured on the corn+wheat fixture: 14 driver
    ids appear on both boards and ``flash_drought`` resolves to two DIFFERENT series keys."""

    contract: str
    driver_id: str
    # -- the DAG's own declaration ------------------------------------------------------------------
    sign: str = ""                       # the driver's effect on the CONTRACT's target metric
    sign_words: Optional[str] = None
    lag: str = ""
    lag_band: Optional[LagBand] = None
    confidence: str = "medium"
    mechanism: str = ""
    driver_type: str = ""
    silver_status: str = "none"
    # -- what the board read ------------------------------------------------------------------------
    series_key: str = ""
    measured: bool = False
    level_shown: Optional[float] = None
    unit: str = ""
    narrate_unit: str = ""
    percentile: Optional[float] = None
    z: Optional[float] = None
    run_direction: str = ""
    run_length: Optional[int] = None
    run_since: str = ""
    level_date: str = ""
    knowledge_date: str = ""
    convention_label: str = ""
    move: float = 0.0                    # the newest change window's delta -- the hop's move TODAY
    # -- the text half ------------------------------------------------------------------------------
    event_date: Optional[str] = None
    event_precision: str = ""
    event_open: bool = False
    event_receipt: Optional[dict] = None
    receipts_top: tuple = ()
    # -- derived ------------------------------------------------------------------------------------
    tail: float = 0.0                    # max(|pct-50|/50, min(|z|/2.5, 1)) in [0, 1] -- the LATEST
    seat: int = 10 ** 6                  # this row's seat in `Board.order` -- the declared tie-break
    # -- the declared lag window's own loudest reading (owner ruling 5, 2026-09-18) -------------------
    tail_peak: float = 0.0               # the same measure, at its loudest inside the lag window
    tail_peak_percentile: Optional[float] = None
    tail_peak_date: str = ""             # when that reading printed
    tail_window_from: str = ""           # the window's own opening -- as-of minus the declared lag
    tail_lag_to: str = ""                # where the declared lag runs to FROM the peak
    # -- THE 09-23 FIX ROUND (CONTRACT C7 / C8) ------------------------------------------------------
    #: WHAT THE DATED DOCUMENT ON THIS HOP IS -- one of :data:`EVENT_KINDS` wherever :func:`chain_hop`
    #: classified it (:func:`hop_event`), and ``""`` on a hop built by hand, which every reader resolves
    #: through :func:`hop_event_kind` -- HEAD's own reading of ``event_open`` / ``event_date`` -- so a
    #: stand-in and a walked hop can never be read two ways.
    event_kind: str = ""
    #: THE INTERVAL THE EVENT DATE COVERS AT ITS PRECISION -- ``(ISO start, ISO end)``; a year-precision
    #: date is its whole year, never its first day (cotton FA-5: "dated January 2026" for "during 2026").
    event_interval: tuple = ()
    #: THE DECLARED PHASE PAIR (``state_conventions.yaml`` ``phase_pairs``) as this hop meets it, read
    #: off ``render.phase_for_state`` -- the estate's ONE phase producer -- and never re-derived here.
    #: ``phase_driver`` is this hop's own id when it names a pole of a declared pair, ``""`` otherwise;
    #: ``phase_in_force_driver`` is the pole the reading puts in force, ``""`` when neither is;
    #: ``phase_in_force`` is True / False for a pole member and None for any other hop; and
    #: ``phase_orient`` is the SIDE of the record this hop's pole names (+1 the positive pole, -1 the
    #: negative, 0 none).
    phase_driver: str = ""
    phase_in_force: Optional[bool] = None
    phase_in_force_driver: str = ""
    phase_orient: int = 0
    #: WHERE THE EFFECT OF THE NEWEST READING CLOSES (CONTRACT C8, :func:`effect_window`'s ``closes``):
    #: the newest print plus the declared maximum lag. ``tail_lag_to`` beside it is the same window
    #: counted from the PEAK (``peak_closes``). ``""`` where the band declares no end.
    effect_closes: str = ""
    #: THE READ'S OWN CROSS-SECTION COLLAPSE (``StateRow.collapse``: ``"mean"`` over cells, ``"sum"`` over
    #: destinations, ``""`` for one cell), carried so the chain line names the row exactly as its SB-1 line
    #: does (review RA M1, ``render.chain_hop_name``); ``None`` on a hop the builder did not measure.
    collapse: Optional[str] = None
    #: THE DRIVER IDS FOLDED INTO THIS LINK (CONTRACT K12, the 09-24 re-smoke's item 21): a composed path
    #: that walks ONE SERIES through two consecutive DAG nodes is ONE link, and the second node's id is
    #: kept here rather than dropped -- MEASURED on the max turn, ``soybean_crush_margin -> board_crush``
    #: both read ``cbot_board_crush_margin|_global|`` (level 2.6038, the 91.58th percentile) and the link
    #: between them was "aligned" by construction and counted as an agreeing hop. ``()`` on every hop
    #: that folded nothing, which is every hop of every path that never walks one series twice.
    aliases: tuple = ()

    @property
    def phase_reoriented(self) -> bool:
        """IS THIS HOP'S TAIL SCORED ON ITS OWN POLE rather than on the reading's unsigned distance?
        True exactly when the hop names one pole of a declared pair and the OTHER pole is in force
        (the 2024-03-01 La Nina chain ranked first on ONI +1.99 degC). Where neither pole is in force
        nothing is re-oriented: the reading sits inside the line and is neither phase's (W-7)."""
        return bool(self.phase_driver and self.phase_in_force_driver
                    and self.phase_driver != self.phase_in_force_driver and self.phase_orient)

    @property
    def key(self) -> tuple:
        return (self.contract, self.driver_id)

    @property
    def chain_tail(self) -> float:
        """THE CHAIN'S OWN TAIL MEASURE: the LOUDEST reading inside this hop's declared lag window
        ending at the as-of (owner ruling 5, 2026-09-18), never the last print alone.

        A shock is IN TRANSIT for the length of its declared lag: a reading that peaked at the 97th
        percentile three months ago and has eased to the 80th is still acting on the next hop while the
        declared window runs. ``tail`` (the latest reading) stays the SB-1 figure and the window peak is
        the chain's -- and the chain row prints BOTH, so a reader is never handed a peak wearing
        today's date. It is a MAX rather than the peak alone because a card whose latest print sits
        outside its own lag window (a stale annual series) would otherwise lose the reading the board
        actually carries."""
        return max(float(self.tail or 0.0), float(self.tail_peak or 0.0))

    @property
    def fold_key(self) -> tuple:
        """THE DIVERSITY FOLD -- ONE SERIES, ONE READING, ONE SPELLING.

        Two hops are the SAME reading when they are served by the same series key, which is how a
        globally-keyed ref (``oni_climate``) and its same-series alias (``oni_lag_climate``) are one
        print and not two. Without it the block renders ``El_Nino -> ...`` and ``La_Nina -> ...`` as
        two chains off ONE ONI reading -- the exact defect the pre-arm fix lane closed on four other
        surfaces (`_series_fold` / `fold_relation` / `group_keep`). A hop with NO series folds on its
        own ``(contract, driver_id)``, because an unmeasured hop is nobody else's reading."""
        return ("series", self.series_key) if self.series_key else ("node", self.contract,
                                                                    self.driver_id)

    @property
    def quantity_key(self) -> tuple:
        """THE QUANTITY THIS HOP READ -- ``()`` where the hop carries no measured standing (the 09-25 fix
        round, item W-3 / N7).

        TWO SERIES KEYS CAN NAME ONE QUANTITY. MEASURED on the 09-25 2024-03-01 turn, chain 2: poultry
        expansion read ``consumption|soybean_meal_cbot|United States`` (the PSD sheet's consumption_mt)
        and soybean-meal feed demand read ``psd_meal_feed_waste_use|soybean_meal_cbot|United States`` (the
        attributes sheet's Feed Waste Dom. Cons.) -- two cards, one number: 34.18 MMT for 2020/21 at the
        97th percentile, z 1.34, because US meal's domestic use IS its feed-and-waste use. The chain walked
        one quantity into itself and scored the link "aligned" -- an identity, not an agreement.

        THE IDENTITY IS MEASURED, NEVER SPELLED: the card's analyst unit (``narrate_unit`` -- the scale
        the shown value is in, so a native ``MT`` card and a native ``1000 MT`` card compare), the scope
        the series key names (commodity and country), the period the reading is for, the shown value,
        AND the reading's standing in its own record (z and percentile) -- two names of one quantity carry
        one record, so a coincidence of one print between two different quantities does not fold. The
        values are compared at nine significant figures (float representation, not a domain threshold).
        A hop with no standing (no z and no percentile) has no measured identity and returns ``()``. The
        rejected lexical form: a table of synonym refs ("consumption" == "feed waste")."""
        if not self.measured or self.level_shown is None or (self.z is None and self.percentile is None):
            return ()
        parts = (str(self.series_key or "").split("|") + ["", "", ""])[:3]

        def _g(v):
            return None if v is None else format(float(v), ".9g")
        return ("quantity", str(self.narrate_unit or ""), parts[1], parts[2], str(self.level_date or ""),
                _g(self.level_shown), _g(self.z), _g(self.percentile))

    @property
    def reading_keys(self) -> frozenset:
        """EVERY IDENTITY UNDER WHICH THIS HOP IS "THE SAME READING" AS ANOTHER (W-3): its series key
        (:attr:`fold_key` -- one series, one reading, including a same-series offset alias) and its
        measured quantity (:attr:`quantity_key` -- two cards, one number). Two hops are one reading when
        these sets meet."""
        qk = self.quantity_key
        return frozenset((self.fold_key, qk)) if qk else frozenset((self.fold_key,))

    def to_dict(self) -> dict:
        return {"contract": self.contract, "driver_id": self.driver_id, "sign": self.sign,
                "lag": self.lag, "confidence": self.confidence, "measured": self.measured,
                "series_key": self.series_key, "level_shown": self.level_shown, "unit": self.unit,
                "percentile": self.percentile, "z": self.z, "run_direction": self.run_direction,
                "run_length": self.run_length, "level_date": self.level_date,
                "knowledge_date": self.knowledge_date, "tail": round(self.tail, 4),
                "tail_peak": round(self.tail_peak, 4),
                "tail_peak_percentile": self.tail_peak_percentile,
                "tail_peak_date": self.tail_peak_date, "tail_lag_to": self.tail_lag_to,
                "event_date": self.event_date, "event_open": self.event_open,
                "silver_status": self.silver_status,
                # THE 09-23 FIX ROUND'S FACTS, appended at the tail of the row so every banked reader
                # of the keys above reads what it read (CONTRACT C7 / C8).
                "event_kind": self.event_kind, "event_precision": self.event_precision,
                "event_interval": list(self.event_interval or ()),
                "phase_driver": self.phase_driver, "phase_in_force": self.phase_in_force,
                "phase_in_force_driver": self.phase_in_force_driver,
                "phase_orient": int(self.phase_orient), "effect_closes": self.effect_closes,
                # THE 09-24 FIX ROUND (CONTRACT K12), at the tail: the node ids folded into this link.
                "aliases": list(self.aliases or ())}


@dataclass
class Chain:
    """ONE composed chain -- driver hops on one anchor DAG plus at most ONE EARNED cross hop.

    ``hops`` is the shallowest parent chain ``[top, ..., bottom]`` that ``ancestor_paths`` already
    walked (so the chain leg costs the walk NOTHING beyond the composition), and ``cross`` is one
    ``inter_commodity`` edge of that DAG whose far board the turn ACTUALLY PRICED.

    **THE CROSS HOP IS EARNED, NEVER FREE.** A far market with nothing measured on it is a NAME, and a
    name buys no rank -- that is the direct fix for the PM's reading of "declared on twenty-three other
    markets, twenty-two in the same direction" as scoring machinery. The earned-cross rule REMOVES NO
    CHAIN: it removes the chain's cross EXTENSION, and the intra-DAG chain stays in the pool with its
    own score and its own rank.

    ``agreements`` is aligned to ``hops``: ``agreements[i]`` is the verdict for hop ``i`` onto hop
    ``i+1``, and the last entry is the verdict onto the TERMINAL (the cross hop's far reading, or the
    anchor's own price where there is no cross). A chain is NEVER ranked down for disagreeing --
    disagreement is where convexity lives and it is a FIELD, never a filter (owner, 2026-09-17)."""

    contract: str
    asof: str = ""                       # the board's own as-of -- B.4's recency bound reads it
    hops: tuple = ()                     # (ChainHop, ...)
    agreements: tuple = ()               # (verdict word, ...) aligned to `hops`
    edge_signs: tuple = ()               # the DECLARED relative sign per hop pair
    cross: Optional[dict] = None         # the earned `bd.edges` row, plus `far_*` facts
    terminal: str = ""                   # the contract slug this chain reaches
    terminal_key: Optional[tuple] = None  # (contract, driver_id) of the far reading, when priced
    terminal_level: Optional[float] = None
    terminal_unit: str = ""
    terminal_percentile: Optional[float] = None
    depth: int = 0
    # -- the rank ------------------------------------------------------------------------------------
    score: float = 0.0
    terms: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)      # one printable sentence per term
    scope: dict = field(default_factory=dict)      # the DATA SCOPE the arithmetic line states (6a)
    #: WHERE THE CROWD IS, AND WHICH WAY (owner ruling 1) -- ``{percentile, against, key}``, and EMPTY
    #: where the clause does not fire, so the page's positioning row is absent rather than a zero
    #: wearing a claim. ``key`` is the ``(contract, driver_id)`` pair the standing is cited at (E11:
    #: ``cot_mm_positioning`` is a row of every futures board this turn carries, so the id alone would
    #: address another market's row). The POINTS this fact is worth ride ``terms['asymmetry']``; this
    #: dict is the fact itself, which is what a page prints and a census checks the points against.
    positioning: dict = field(default_factory=dict)
    receipt_index: int = 0
    receipt: Optional[dict] = None
    receipt_kind: str = "none"           # open | closed | mechanism | none
    receipt_words: str = ""
    #: HOW MANY DATED ACTIONS THIS CHAIN HAD AND COULD NOT USE -- a CLOSED receipt whose window had
    #: shut more than one band-length before the as-of (:func:`_receipt_in_reach`). The estate HAD the
    #: document and the chain's own window had closed on it, which is a different fact from never
    #: having one, and a fence CORRECTS or COMPUTES and never deletes: the receipt does not score, and
    #: it is COUNTED here and in :func:`chain_counts` rather than silently dropped (review MA-4).
    #:
    #: IT IS THE PER-CHAIN COUNT AND IT STAYS ONE (round-4 census 3): the COUNT LINE's own key folds
    #: the same documents over the pool by their own identity, because a memoised hop rides every
    #: chain that walks it and chains x documents is not a document count.
    receipts_aged_out: int = 0
    #: WHERE THE NEWEST OF THOSE DOCUMENTS SITS, AND WHEN IT IS DATED (round-4 census 4). The aged date
    #: is a ``max`` over whichever hops aged out, so a row that names the chain's RECEIPT hop beside it
    #: prints a dated fact under a relation the producer never declared it against -- the page said
    #: "at cot mm positioning, a dated action on 2019-01-01, aged out of the window declared for it"
    #: about a document sitting on ``La_Nina``. The producer knows which hop it was; these two names
    #: are how a consumer can say it. Both are ``None`` / ``""`` where nothing aged out.
    aged_receipt_hop: Optional[ChainHop] = None
    aged_receipt_date: str = ""
    #: A DATED REPORT SENTENCE (a `date`, no `event_date`) THE MECHANISM BOUND REFUSED (round-5 census
    #: blocker 1 / handoff W5-O3(4)). Choice (3) now reads the same window as choice (2), so a report
    #: sentence older than one band-length of the as-of scores EVENT 0 -- and until this field it was
    #: named nowhere and counted nowhere, while the render could still print it as the chain's receipt.
    #: It is its OWN population under its OWN noun ("a dated report", never "a dated action"):
    #: `receipts_aged_out` counts ACTIONS and folding report sentences under that noun would be one
    #: name over two populations. Both are ``None`` / ``""`` where nothing was refused.
    mechanism_refused_hop: Optional[ChainHop] = None
    mechanism_refused_date: str = ""
    #: WHAT THE DOCUMENT THIS CHAIN WAS RECEIPTED ON IS (CONTRACT C7) -- one of :data:`EVENT_KINDS`,
    #: BESIDE :attr:`receipt_kind` and never instead of it: ``receipt_kind`` keeps HEAD's four POINTS
    #: words (:data:`EVENT_KIND_RECEIPT` maps one to the other) so every banked score reads as it did.
    #: Set by :func:`_chain_receipt` from the SAME branch that chose the receipt, so the word and the
    #: points can never describe two documents.
    event_kind: str = "none"
    #: WHICH LIVE QUESTION SLOTS THIS CHAIN ANSWERS (``subject`` / ``pair`` / ``horizon``), stamped by
    #: :func:`chain_render_set` on every pool chain from the same slot tests that seat one. A LABEL,
    #: never an input: :func:`chain_trace_set` reads it to carry each live slot's best candidate on
    #: the bounded payload.
    slot_fits: tuple = ()
    #: **A PREMISE NOT IN FORCE** (CONTRACT K13, the 09-24 re-smoke's item 22): the chain's FIRST hop names
    #: one pole of a declared phase pair while the OTHER pole is in force (``render.phase_for_state``, read
    #: through :func:`hop_phase`). The chain's premise is off, so it declares no direction, earns no
    #: ASYMMETRY credit and takes no seat of any kind -- it stays in the pool, keeps its score and its
    #: trace row, and is COUNTED (``chain_counts["premise_off"]``). MEASURED: max chain 3 (corn / La_Nina
    #: at ONI +1.8) took a top seat at 71.6 on a positioning tail; soyoil's subject seat was IOD_positive,
    #: not in force. The round-1 phase fix reached only the phase HOP's own tail and words.
    premise_off: bool = False
    #: WHICH TERMINAL READING THE LAST LINK'S VERDICT READ (CONTRACT K10): ``{"source", "series_key",
    #: "sign"}`` -- ``source`` is ``tape`` (the far contract's OWN price move, where the board read its
    #: tape), ``same_driver`` (the far board's row of the SAME driver id as the last hop) or
    #: ``undetermined`` (neither was read, or the far row is the last hop's own series); EMPTY on a
    #: chain with no cross hop, whose terminal verdict is HEAD's. ``sign`` is the declared relative sign
    #: the verdict was taken under. The earned cross's own far reading (``cross["far_series_key"]``) is
    #: a REACH fact and never a verdict input.
    terminal_reading: dict = field(default_factory=dict)
    #: THE LEXICAL TIER OF THE SUBJECT PICK THIS CHAIN CARRIES (CONTRACT K9, OWNER DECISION O-5):
    #: ``exact`` / ``alias`` when the question's own words named the driver (by any spelling of its
    #: group), ``semantic`` when the pick is an inference; the best tier among the picks whose group ids
    #: this chain's hops carry on its own contract. ``""`` on a chain that answers no subject. The seat
    #: label reads it: "the chain this question names" only for a lexical pick.
    subject_tier: str = ""
    #: THE CHAIN THAT ANSWERS THE ASKED HORIZON (CONTRACT K21) -- True on exactly the one rendered chain
    #: the horizon slot seated or found already on the page; the head's horizon row prints ITS outcome.
    answers_horizon: bool = False
    history: dict = field(default_factory=dict)
    outcome: dict = field(default_factory=dict)
    # -- the direction (owner, 2026-09-17: disagreement must be STRUCTURAL) --------------------------
    unnamed_terminal: bool = False       # the terminal is a market the question did not name
    declared_sign: str = ""              # what the graph declares this chain does to the anchor
    direction: str = "unsettled"         # higher | lower | unsettled
    side: str = "unsettled"              # for | against | unsettled -- the same fact, the owner's words
    against_hops: tuple = ()             # the hops running AGAINST their declared direction today
    curated: str = ""                    # the curated chain id whose hops this one contains
    # -- the render decision -------------------------------------------------------------------------
    rendered: bool = False
    full: bool = False                   # full block vs ONE line with its arithmetic
    #: WHICH SEAT THIS CHAIN TOOK -- a :data:`CHAIN_SLOTS` word on every picked chain, ``''`` on every
    #: chain that did not render. It is a LABEL and never an input: the rank is the graph's and a slot
    #: only decides whether a seat was reserved for it (owner ruling 2026-09-22).
    slot: str = ""
    decline: Optional[str] = None        # a CHAIN_REASONS word, never a removal

    # ── the printable identity ──────────────────────────────────────────────────────────────────────
    @property
    def top(self) -> Optional[ChainHop]:
        return self.hops[0] if self.hops else None

    @property
    def receipt_hop(self) -> Optional[ChainHop]:
        return self.hops[self.receipt_index] if self.hops else None

    @property
    def hop_ids(self) -> tuple:
        return tuple(h.driver_id for h in self.hops)

    @property
    def measured_hops(self) -> int:
        return sum(1 for h in self.hops if h.measured)

    @property
    def rank(self) -> tuple:
        """DESIGN B.2's tie-break, verbatim: shorter depth first, then the RECEIPT hop's own seat on
        the board, then the driver id. The two trailing terms are this module's own determinism and
        decide nothing a reader can see -- two chains that agree on all five are the same chain."""
        rh = self.receipt_hop
        tt = self.terminal_percentile
        return (-round(self.score, 4), self.depth,
                rh.seat if rh is not None else 10 ** 6,
                rh.driver_id if rh is not None else "",
                self.hops[0].driver_id if self.hops else "",
                # THE TERMINAL'S OWN DISTANCE FROM ITS MIDDLE, and it is a DECLARED ADDITION to DESIGN
                # B.2's list rather than a silent one. B.2's tie-break ends at the driver id, which
                # leaves every cross variant of one path tied on all five terms -- and two chains that
                # differ only in WHICH priced far market they reach are still two different answers
                # for a reader, so the alphabet was deciding which market the page named. Ranking
                # those by the far market's OWN distance from its middle is the TAIL rule applied to
                # the terminal, it decides NOTHING between chains that differ anywhere above it, and
                # it moves no score.
                -(abs(float(tt) - 50.0) / 50.0 if tt is not None else 0.0), self.terminal)

    def fold_keys(self) -> tuple:
        """The TWO keys the diversity rule folds on: the TOP hop's reading and the RECEIPT hop's."""
        rh = self.receipt_hop
        return (self.hops[0].fold_key if self.hops else ("node", self.contract, ""),
                rh.fold_key if rh is not None else ("node", self.contract, ""))

    def fold_idents(self) -> tuple:
        """THE TWO IDENTITY SETS THE DIVERSITY RULE FOLDS ON (the 09-25 fix round, W-3): the TOP hop's
        :attr:`ChainHop.reading_keys` and the RECEIPT hop's -- the series key AND the measured quantity,
        so two chains whose top readings are one quantity under two series keys share a reading exactly
        as two chains on one series key do. :meth:`fold_keys` is kept as the series-key pair."""
        rh = self.receipt_hop
        top = self.hops[0].reading_keys if self.hops else frozenset((("node", self.contract, ""),))
        rec = rh.reading_keys if rh is not None else frozenset((("node", self.contract, ""),))
        return top, rec

    def to_dict(self) -> dict:
        """The trace row. NO ARRAYS -- the history stat's own counts, never its inputs (A.7)."""
        return {"contract": self.contract, "hops": [h.to_dict() for h in self.hops],
                "agreements": list(self.agreements), "edge_signs": list(self.edge_signs),
                "cross": (None if not self.cross else
                          {k: self.cross.get(k) for k in
                           ("other", "direction", "relation", "sign", "lag", "far_driver_id",
                            "far_series_key", "far_percentile", "far_level")}),
                "terminal": self.terminal, "depth": self.depth,
                "score": round(self.score, 1), "terms": dict(self.terms),
                "notes": dict(self.notes), "scope": dict(self.scope),
                "positioning": dict(self.positioning),
                "receipt_index": self.receipt_index, "receipt_kind": self.receipt_kind,
                "receipt_words": self.receipt_words,
                "receipts_aged_out": int(self.receipts_aged_out),
                # WHICH HOP THE AGED DOCUMENT SAT ON, ON THE TRACE ROW TOO (census 4) -- the id and
                # not the object, because a trace row carries no objects (A.7).
                "aged_receipt_hop": (self.aged_receipt_hop.driver_id
                                     if self.aged_receipt_hop is not None else ""),
                "aged_receipt_date": self.aged_receipt_date,
                "mechanism_refused_hop": (self.mechanism_refused_hop.driver_id
                                          if self.mechanism_refused_hop is not None else ""),
                "mechanism_refused_date": self.mechanism_refused_date,
                "history": {k: v for k, v in self.history.items() if k != "firings"},
                "outcome": {k: v for k, v in self.outcome.items() if k != "moves"},
                "declared_sign": self.declared_sign, "direction": self.direction, "side": self.side,
                "against_hops": list(self.against_hops), "curated": self.curated,
                "rendered": self.rendered, "full": self.full, "slot": self.slot,
                "decline": self.decline,
                # APPENDED AT THE TAIL (the 09-23 fix round, CONTRACT C7): the chain's own event word
                # and the live question slots it answers.
                "event_kind": self.event_kind, "slot_fits": list(self.slot_fits or ()),
                # APPENDED AT THE TAIL (the 09-24 fix round, CONTRACT K9 / K10 / K13 / K21).
                "premise_off": bool(self.premise_off),
                "terminal_reading": dict(self.terminal_reading or {}),
                "subject_tier": self.subject_tier, "answers_horizon": bool(self.answers_horizon)}


# ── the hop's facts, memoised ────────────────────────────────────────────────────────────────────────
def hop_window_peak(st, band: Optional[LagBand], asof: str, *, orient: int = 0) -> dict:
    """THE LOUDEST KNOWABLE READING INSIDE ``[as-of - max_lag, as-of]`` (owner ruling 5, 2026-09-18).

    ``{tail, percentile, date, from, to, n}``; all zeros where the row serves no array, declares no
    band, or has no point inside the window -- a decline, never a guess.

    **TWO CALLS TO THE ESTATE'S OWN PERCENTILE AND NOT ONE PER POINT.** The tail measure is monotone in
    the value's distance from its middle and the percentile is monotone in the value, so the window's
    MAXIMUM and MINIMUM are the only two candidates for its loudest reading -- which is why this runs
    in two `stats.percentile` calls per hop rather than one per observation, on a board that composes
    up to 1,848 candidate chains. The basis is the row's OWN served array (the same one the history
    stat reads), so the peak is stated against the same record the latest reading is.

    KNOWABLE-AT-THE-AS-OF ONLY: the window closes at the as-of and the arrays are point-in-time by
    construction (`feeders` reads them at the board's as-of), so the two agree rather than one
    correcting the other.

    ``orient`` IS THE HOP'S OWN POLE (+1 / -1) WHERE ITS PHASE IS NOT THE ONE IN FORCE (the 09-23 fix
    round, :attr:`ChainHop.phase_reoriented`), and 0 -- HEAD's unsigned reading -- everywhere else. A
    La Nina hop's loudest reading inside its window is the window's MINIMUM, scored by how far it sits
    BELOW the middle; the window's maximum is the warm phase's reading and is not this hop's at all. So
    an oriented peak reads ONE extreme on ONE side, and a window with no reading on the hop's own side
    has no peak (``tail`` 0, no date) rather than borrowing the other pole's."""
    out = {"tail": 0.0, "percentile": None, "date": "", "from": "", "to": "", "n": 0}
    if st is None or band is None or band.min_q is None or not asof:
        return out
    vals, dates, _u = hop_arrays(st)
    if not vals or len(vals) != len(dates):
        return out
    lo_m, hi_m = band.months()
    hi = int(hi_m) if hi_m is not None else max(int(lo_m or 0), QUARTER_MONTHS)
    hi = max(1, hi)
    start = _add_months(str(asof)[:10], -hi) or ""
    i0 = _at_or_after(dates, start)
    i1 = _at_or_before(dates, str(asof)[:10])
    if i0 is None or i1 is None or i1 < i0:
        return out
    window = [(float(vals[i]), str(dates[i])[:10]) for i in range(i0, i1 + 1)]
    out["from"], out["n"] = start, len(window)
    extremes = ((max(window), min(window)) if not orient else
                ((max(window),) if int(orient) > 0 else (min(window),)))
    for v, d in extremes:
        pc = ST.percentile(v, list(vals))
        if pc.get("declined"):
            continue
        t = _hop_tail(pc.get("value"), None, orient=orient)
        if t > out["tail"]:
            out.update({"tail": t, "percentile": pc.get("value"), "date": d,
                        "to": _add_months(d, hi) or ""})
    return out


def chain_hop(bd: B.Board, row: B.NodeRow, *, seat: Optional[dict] = None,
              receipts: Optional[dict] = None) -> ChainHop:
    """ONE :class:`ChainHop` from a board row. ZERO reads -- every figure is already on the board.

    **THE 09-23 FIX ROUND READS THREE MORE FACTS HERE, EACH FROM ITS ONE PRODUCER, AND WRITES NONE OF
    THEM BACK TO THE ROW** (CONTRACT C7 / C8):

      * the DATED DOCUMENT's kind (:func:`hop_event`) over the SAME receipt list step 5 read for this
        row -- ``receipts`` is the walk's own ``{(contract, driver_id): [...]}`` map, threaded by
        :func:`chain_rows`; absent (the offline harness, a hand-built board) the row's own step-5
        winner is the list. ``row.event_open`` / ``row.event_date`` are NEVER written: they feed the
        loud set's re-take (step 5) and the board-on / chain-off bytes (W-6), so the chain's reading
        of the document lives on the HOP and nowhere else;
      * the PHASE (:func:`hop_phase`, over ``render.phase_for_state``): a hop that names one pole of a
        declared pair while the OTHER pole is in force scores its TAIL -- latest and window peak alike
        -- on its own pole (W-7), so a La Nina hop reads 0 on a warm ONI instead of the warm tail;
      * the EFFECT WINDOW (:func:`effect_window`): ``tail_lag_to`` is its ``peak_closes`` (byte for
        byte HEAD's ``peak + max lag`` on every bounded band) and ``effect_closes`` is its ``closes``."""
    st = row.state
    ok = st is not None and status_word(st.status) == "ok"
    pct = _measure_value(st.percentile) if ok else None
    z = _measure_value(st.z) if ok else None
    run = (st.run or {}) if ok else {}
    if run.get("declined"):
        run = {}
    asof = str(getattr(bd, "asof", "") or "") if bd is not None else ""
    # THE PHASE, READ ONCE PER HOP. `orient` is non-zero only where the hop's own pole is not the one in
    # force; every other hop -- and every hop on a board whose readings are inside the line -- keeps
    # HEAD's unsigned measure exactly.
    ph = hop_phase(row.driver_id, st if ok else None)
    orient = int(ph["phase_orient"]) if _phase_reorients(ph) else 0
    # THE DECLARED LAG WINDOW'S OWN LOUDEST READING (owner ruling 5, 2026-09-18). It is computed HERE
    # because the hop is memoised per `(contract, driver_id)` -- one window read per row of the board,
    # never one per candidate chain -- and it costs zero reads: the array is already on the row.
    pk = hop_window_peak(st if ok else None, row.lag_band, asof, orient=orient)
    ew = effect_window(row.lag_band, newest=str((st.level_date if ok else "") or ""),
                       run_start=str(run.get("since_date") or "") or None,
                       peak=str(pk["date"] or "") or None)
    # THE DATED DOCUMENT, CLASSIFIED ON THE CHAIN'S OWN PATH. The list is the one step 5 read for this
    # row (the same lookup, key then bare id); the row's own step-5 stamp rides as `stamped` so the
    # winner it already read is read the same way and not re-derived.
    if receipts is not None:
        rs = receipts.get(row.key) or receipts.get(row.driver_id) or ()
    else:
        rs = (row.event_receipt,) if row.event_receipt else ()
    ev = hop_event(rs, asof=asof, band=row.lag_band or parse_lag(""), node_type=row.type or "",
                   stamped={"event_date": row.event_date, "event_open": row.event_open,
                            "event_precision": row.event_precision})
    return ChainHop(
        contract=row.contract, driver_id=row.driver_id, sign=row.sign or "",
        sign_words=SIGN_WORDS.get(row.sign) if row.sign else None, lag=row.lag or "",
        lag_band=row.lag_band, confidence=row.confidence or "medium",
        mechanism=row.mechanism or "", driver_type=row.type or "",
        silver_status=row.silver_status or "none",
        series_key=row.series_key or "", measured=bool(ok),
        level_shown=(st.level_shown if ok else None), unit=(st.unit if ok else ""),
        narrate_unit=(st.narrate_unit if ok else ""),
        percentile=pct, z=z,
        run_direction=str(run.get("direction") or ""),
        run_length=(int(run["length"]) if str(run.get("length") or "").strip().lstrip("-").isdigit()
                    else None),
        run_since=str(run.get("since_date") or ""),
        level_date=str((st.level_date if ok else "") or ""),
        knowledge_date=str((st.knowledge_date if ok else "") or ""),
        convention_label=str(((st.convention or {}).get("label") if ok else "") or ""),
        move=_newest_move(st) if ok else 0.0,
        event_date=ev["event_date"], event_precision=ev["precision"],
        event_open=(ev["kind"] == "action_open"), event_receipt=ev["receipt"],
        receipts_top=tuple((row.receipts or {}).get("top") or ()),
        tail=_hop_tail(pct, z, orient=orient),
        seat=int((seat or {}).get(row.key, 10 ** 6)),
        tail_peak=float(pk["tail"]), tail_peak_percentile=pk["percentile"],
        tail_peak_date=str(pk["date"]), tail_window_from=str(pk["from"]),
        tail_lag_to=str(ew["peak_closes"] or ""),
        event_kind=ev["kind"], event_interval=tuple(ev["interval"] or ()),
        phase_driver=ph["phase_driver"], phase_in_force=ph["phase_in_force"],
        phase_in_force_driver=ph["phase_in_force_driver"], phase_orient=int(ph["phase_orient"]),
        effect_closes=str(ew["closes"] or ""),
        collapse=(str(getattr(st, "collapse", "") or "") if ok else None))


def hop_phase(driver_id: str, st) -> dict:
    """THE DECLARED PHASE PAIR AS ONE HOP MEETS IT -- ``{phase_driver, phase_in_force,
    phase_in_force_driver, phase_orient}`` (the 09-23 fix round, W-7).

    ONE PRODUCER, READ AND NEVER RE-DERIVED: ``render.phase_for_state`` (the estate's ONE phase verdict,
    over ``state_conventions.yaml``'s ``phase_pairs`` and the convention's own first band) says which
    pole the reading puts in force and whether it clears the line; ``render.phase_in_force`` at the
    band itself says which member of the declared pair is the POSITIVE pole. Nothing here names an id:
    a hop is a pole member because the pair DECLARES its driver id, and a hop on a card with no declared
    pair gets the empty answer -- which is every hop but the four ENSO / IOD poles today.

    The pole's SIDE (``phase_orient``) is +1 for the pair's positive member and -1 for its negative
    one. ``phase_in_force_driver`` is ``""`` when the reading sits inside the line -- neither pole is
    in force, and :attr:`ChainHop.phase_reoriented` then re-orients nothing (ONI +0.3 degC)."""
    out = {"phase_driver": "", "phase_in_force": None, "phase_in_force_driver": "",
           "phase_orient": 0}
    if st is None:
        return out
    try:
        from leviathan.graphrag.state.render import phase_for_state, phase_in_force
        pf = phase_for_state(st) or {}
    except Exception:                                   # noqa: BLE001 -- a phase read never kills a walk
        return out
    if not pf:
        return out
    in_force = str(pf.get("driver") or "") if pf.get("in_force") else ""
    out["phase_in_force_driver"] = in_force
    members = {str(pf.get("driver") or ""), str(pf.get("other_driver") or "")} - {""}
    did = str(driver_id or "")
    if did not in members:
        return out
    try:
        pos = str((phase_in_force(getattr(st, "table", ""), getattr(st, "metric", ""),
                                  abs(float(pf.get("band") or 0.0))) or {}).get("driver") or "")
    except (TypeError, ValueError):
        pos = ""
    out["phase_driver"] = did
    out["phase_in_force"] = bool(in_force) and in_force == did
    out["phase_orient"] = (1 if did == pos else -1) if pos else 0
    return out


def _phase_reorients(ph: dict) -> bool:
    """:attr:`ChainHop.phase_reoriented`'s rule over :func:`hop_phase`'s dict -- ONE rule, two readers."""
    return bool(ph.get("phase_driver") and ph.get("phase_in_force_driver")
                and ph.get("phase_driver") != ph.get("phase_in_force_driver")
                and ph.get("phase_orient"))


def effect_window(band: Optional[LagBand], *, newest: str, run_start: Optional[str] = None,
                  peak: Optional[str] = None) -> dict:
    """THE ONE LAG PRODUCER FOR "WHEN DOES THIS READING'S EFFECT LAND, AND WHEN IS IT SPENT"
    (CONTRACT C8) -- ``{opens, closes, peak_closes, anchor}``.

    **ONE RULE: A READING STILL IN ITS RUN KEEPS ACTING UNTIL THE MAXIMUM LAG AFTER ITS NEWEST PRINT;
    THE RUN'S START ONLY OPENS THE WINDOW.** ``opens`` is ``(run_start or newest) + band.min``;
    ``closes`` is ``newest + band.max``; ``peak_closes`` is ``peak + band.max`` -- where the window's
    loudest reading's own effect runs to, which is what the chain's ``tail_lag_to`` has always printed.
    MEASURED on the 09-23 re-smoke: the SB-J line counted the whole window from the run's start and
    printed "closed around August 2026" for an ONI still rising at +1.8 degC (corn_wheat F4) while the
    chain on the same page carried the lag to April 2027 -- two producers, two windows, one reading.

    BOUNDED BY CONSTRUCTION (W-9): ``closes`` is counted from the NEWEST print and the run start never
    enters it, so a run that began in 1997 opens early and still closes at newest + max lag.

    THE BAND'S MAXIMUM IS FLOORED AT ONE MONTH, which is :func:`hop_window_peak`'s own floor: a peak is
    measured over a window of at least one month, and the window its effect runs to is the same width,
    so a zero-quarter band keeps HEAD's ``peak + 1 month`` byte for byte. AN OPEN-ENDED BAND CLOSES
    NOWHERE (``structural`` opens and does not close, :func:`event_is_open`'s own law): ``closes`` and
    ``peak_closes`` are ``None`` rather than an invented date. A band with no parse declines to ``None``
    everywhere. ``anchor`` says which date opened the window (``run`` / ``reading``)."""
    anchor = "run" if run_start else "reading"
    out = {"opens": None, "closes": None, "peak_closes": None, "anchor": anchor}
    if band is None or band.min_q is None:
        return out
    lo_m, hi_m = band.months()
    start = str(run_start or newest or "")
    if start:
        out["opens"] = _add_months(start, int(lo_m or 0))
    if hi_m is None:
        return out
    hi = max(1, int(hi_m))
    if newest:
        out["closes"] = _add_months(str(newest), hi)
    if peak:
        out["peak_closes"] = _add_months(str(peak), hi)
    return out


def _measure_value(m):
    """A stats result's ``value``, or ``None`` when the measure declined. A DECLINE IS NOT A ZERO."""
    if not isinstance(m, dict) or m.get("declined"):
        return None
    v = m.get("value")
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _has_move(st) -> bool:
    """Does this reading carry a MOVE the verdict can read -- a non-declined change window with a delta
    (the same loop :func:`_newest_move` reads)? Never a status word."""
    for ch in (getattr(st, "changes", None) or ()):
        if not isinstance(ch, dict) or ch.get("declined"):
            continue
        try:
            float(ch.get("delta"))
            return True
        except (TypeError, ValueError):
            continue
    return False


def _newest_move(st) -> float:
    """The hop's OWN move today: the newest non-declined change window's delta, else 0.0.

    ``0.0`` IS "UNDETERMINED" AND NOT "FLAT", and `stats.sign_agreement` reads it exactly that way --
    a leg whose move is exactly zero returns ``undetermined`` rather than a verdict. So a row with no
    measurable change never mints an agreement it did not earn."""
    for ch in (getattr(st, "changes", None) or ()):
        if not isinstance(ch, dict) or ch.get("declined"):
            continue
        try:
            return float(ch.get("delta"))
        except (TypeError, ValueError):
            continue
    return 0.0


def _hop_tail(pct, z, *, orient: int = 0) -> float:
    """DESIGN B.2's TAIL measure in [0, 1]: ``max(|pct-50|/50, min(|z|/2.5, 1))``.

    THE TWO READINGS ARE A MAX AND NOT A MEAN because they measure the same thing on two scales and a
    mean would halve a tail a card reports on only one of them (25 of 49 declared cards carry no z at
    all on some vintages). An unmeasured hop is 0.0 -- which is a SCORE, never an exclusion (E3).

    ``orient`` (+1 / -1) READS THE SAME MEASURE ON ONE SIDE ONLY, for a hop that names one pole of a
    declared phase pair while the other pole is in force (the 09-23 fix round, W-7): the distance from
    the middle counts only in the direction of the hop's own pole, so ONI at the 95th percentile and
    +2.03 sigma is a tail of 0.9 for the warm pole and 0.0 for the cool one. 0 is HEAD's unsigned
    reading, byte for byte."""
    best = 0.0
    o = int(orient or 0)
    if pct is not None:
        d = (float(pct) - 50.0) / 50.0
        best = max(best, min(abs(d) if not o else max(0.0, d * o), 1.0))
    if z is not None:
        zz = float(z) / 2.5
        best = max(best, min(abs(zz) if not o else max(0.0, zz * o), 1.0))
    return best


def hop_edge_sign(parent_sign: str, child_sign: str) -> str:
    """The DECLARED relative sign between two adjacent hops -- ``'+'``, ``'-'`` or ``''``.

    **THE SHIPPED SCHEMA DECLARES NO EDGE SIGN BETWEEN TWO DRIVERS AND THIS IS THE ONLY COMPOSITION IT
    LICENSES.** ``Driver.sign`` is "the driver's effect on the contract's ``target_metric``"
    (`causal/schema.py:8-10`, and `path_rank`'s own note says the same of ``lag``), so a parent's sign
    is NOT its sign onto its child. What the two declarations DO fix is their relation: a ``+`` parent
    of a ``+`` child both push the price up, so the parent rising pushes the child up (relative
    ``+``); a ``+`` parent of a ``-`` child pushes it down (relative ``-``). The relative sign is the
    PRODUCT of the two declared signs, and nothing else in the graph says anything about the pair.

    ``'0'`` IS A DECLARED WORD AND IS NOT A SIGN (sec 1.5): an ambiguous driver declines to declare a
    direction, so the pair has no relative sign and the agreement verdict is ``undetermined`` --
    stated, never guessed."""
    a, b = _SIGN_INT.get(str(parent_sign or "")), _SIGN_INT.get(str(child_sign or ""))
    if a is None or b is None:
        return ""
    return "+" if a * b > 0 else "-"


def composed_sign(*signs) -> str:
    """THE DECLARED RELATION ACROSS SEVERAL DECLARED EDGES (CONTRACT K10): the product of the signs, the
    same telescoping :func:`chain_declared_sign` states. ``"0"`` -- a DECLARED "no committed direction"
    (sec 1.5) -- anywhere makes the relation ``"0"``, because a relation through an edge that commits no
    direction commits none; a MISSING sign anywhere makes it ``""`` (nothing declared). Unlike
    :func:`hop_edge_sign`, which reads ``"0"`` as undeclared between two drivers (HEAD), this keeps the
    declared word, so the last link onto a far market says "no committed direction" where the graph did."""
    out = 1
    zero = False
    for sg in signs:
        s = str(sg or "").strip()
        if s == "0":
            zero = True
            continue
        v = _SIGN_INT.get(s)
        if v is None:
            return ""
        out *= v
    if zero:
        return "0"
    return "+" if out > 0 else "-"


def chain_declared_sign(hops, cross_sign: str = "") -> str:
    """What the graph declares THIS CHAIN does to the anchor's own target metric.

    THE PRODUCT OF THE DECLARED SIGNS TELESCOPES ONTO THE TOP HOP'S OWN, and the arithmetic is worth
    writing down because the owner's rule is stated as a product: the relative signs along the chain
    are ``(s0*s1)(s1*s2)...(s_{n-2}*s_{n-1})``, and composing them with the BOTTOM hop's own declared
    sign onto the price gives ``s0 * s1^2 * ... * s_{n-1}^2 = s0``. So a chain's declared direction
    onto the anchor IS its TOP hop's own declared sign -- which is exactly what `ancestor_paths`
    already says of the BAND ("the band on the row is the TOP node's own, never a sum"), arrived at
    from the other end. An EARNED cross hop then carries the chain onto the far board, so the far
    market's direction is that product times the EDGE's own declared sign."""
    if not hops:
        return ""
    top = _SIGN_INT.get(str(hops[0].sign or ""))
    if top is None:
        return ""
    if cross_sign:
        c = _SIGN_INT.get(str(cross_sign or ""))
        if c is None:
            return ""
        top *= c
    return "+" if top > 0 else "-"


# ── the history stat, at zero reads ──────────────────────────────────────────────────────────────────
def hop_arrays(st) -> tuple:
    """``(values, dates, unit)`` off ``StateRow.inputs`` -- the arrays the board ALREADY fetched.

    ``StateRow.inputs`` is ``{key: {values, dates, unit}}`` (`rows.py:305`), written by
    ``feeders.series_state`` / ``tape_state`` / ``state_from_arrays``, never cleared, and already read
    by ``analogs.state_history``. MEASURED on the S8 recon: every loud row with an ``ok`` state on the
    fixture board carries its bundle, 20 to 440 points, and 18 of the 22 measured series on the max
    board start before 2015. **The history term costs ZERO reads.**

    The nulls are dropped through ``transforms.dated_pairs`` -- ONE cleaner, the same one the analog
    selector uses -- because everything below this line places a position on a calendar, and a served
    NULL cell (``pgnumbers._stringify`` renders one as ``""``) would raise on ``float("")``."""
    if st is None:
        return ((), (), "")
    key = st.key.label() if getattr(st, "key", None) is not None else ""
    arrays = (getattr(st, "inputs", None) or {}).get(key) or {}
    if not arrays:
        return ((), (), "")
    mkey = array_memo_key(st, key)
    got = _ARRAY_MEMO.get(mkey)
    if got is not None:
        return got
    from leviathan.graphrag.state import transforms as TR
    vals, dates, _dropped = TR.dated_pairs(arrays.get("values"), arrays.get("dates"))
    got = (tuple(vals), tuple(dates), str(arrays.get("unit") or ""))
    if len(_ARRAY_MEMO) >= 512:
        _ARRAY_MEMO.clear()
    _ARRAY_MEMO[mkey] = got
    return got


def array_memo_key(st, label: str) -> tuple:
    """THE ARRAY MEMO'S KEY -- the series label PLUS the three terms the estate's own memo law requires
    (`feeders.state_cache_key`, review round 2 M2).

    **THE SERIES LABEL ALONE IS A POINT-IN-TIME BREACH AND IT IS THE IMMORTAL KIND.** The label is
    ``ref|commodity|country[|metric]`` (`rows.py:213`) and carries no as-of, no declared offset and no
    mirror epoch, while ``_ARRAY_MEMO`` is a module global with a PROCESS lifetime -- so in a serving
    worker or an eval process (``--workers 4``, many turns, many as-ofs) the second turn's history stat
    was computed on the FIRST turn's array. MEASURED before this key landed: a second reader of
    ``oni_climate|_global|`` was handed ``[1.0, 2.0, 3.0]`` where its own array is ``[1.0 .. 5.0]``,
    and ``feeders.cache_clear()`` did not reach the entry at all. At a different as-of that puts
    post-as-of points inside ``chain_firings`` -- inside a PRINTED figure ("in forty-six of fifty-nine
    past firings") -- and point-in-time is one of the only two hard filters this design allows itself.

    The three terms are exactly the ones ``feeders.state_cache_key``'s own docstring names for the same
    hazard: the AS-OF (a historical board is a different array), the declared same-series OFFSET (the
    palm board's ENSO row is the soybean board's array shifted, and the docstring's own example is that
    hit), and the MIRROR EPOCH (a vintage backfill changes which print a PAST as-of collapses to)."""
    from leviathan.graphrag.state import feeders as _F
    return (str(label or ""), str(getattr(st, "asof", "") or ""),
            int(getattr(st, "offset_months", 0) or 0), _F.mirror_epoch())


def cache_clear() -> None:
    """Drop this module's two memos. REGISTERED ON ``feeders.cache_clear()`` (review round 2 M2), which
    is the estate's ONE clear seam -- the board census calls it between boards, and before this hook the
    array memo survived it and served the previous board's arrays to the next one."""
    _ARRAY_MEMO.clear()
    _DATE_KEY_MEMO.clear()


#: The cleaned ARRAY per :func:`array_memo_key`, bounded exactly as the board's own state memo is
#: (sec 1.1: the cache holds whole arrays and is LRU-bounded at 512). Cleaning is once per SERIES and
#: not once per CHAIN: a max board composes 1,848 candidates over ~30 series, and the profile of the
#: first build put 1.8 seconds of a 2.0-second leg inside `transforms.clean_pairs_counted` and
#: `stats._floats`.
_ARRAY_MEMO: dict = {}


def _at_or_after(dates, iso: str) -> Optional[int]:
    """The first index whose date is at or after ``iso``. The arrays are CHRONOLOGICAL by contract
    (`transforms.dated_pairs` preserves the served order and `feeders` serves it ascending), so this
    is a bisect rather than a scan -- it runs once per firing per chain and the linear form was 1.2 of
    the leg's 2.0 seconds on the max fixture."""
    if not iso:
        return None
    i = bisect.bisect_left(_DATE_KEYS(dates), iso[:10])
    return i if i < len(dates) else None


def _at_or_before(dates, iso: str) -> Optional[int]:
    """The last index whose date is at or before ``iso``, or ``None``."""
    if not iso:
        return None
    i = bisect.bisect_right(_DATE_KEYS(dates), iso[:10]) - 1
    return i if i >= 0 else None


def _DATE_KEYS(dates) -> list:
    """``dates`` as ten-character ISO keys, memoised by identity -- the same tuple is re-searched once
    per firing and the slicing is the whole cost."""
    got = _DATE_KEY_MEMO.get(id(dates))
    if got is not None and got[0] is dates:
        return got[1]
    keys = [str(d)[:10] for d in dates]
    if len(_DATE_KEY_MEMO) >= 512:
        _DATE_KEY_MEMO.clear()
    _DATE_KEY_MEMO[id(dates)] = (dates, keys)
    return keys


_DATE_KEY_MEMO: dict = {}


#: One month in days, read from the estate's ONE cadence table so the conversion below has no second
#: constant (`feeders.CADENCE_DAYS['monthly']`, which is 365/12).
_MONTH_DAYS: float = 365.0 / 12.0


def separation_periods(months, st=None, dates=()) -> int:
    """A band length in MONTHS as a count of THE ARRAY'S OWN PERIODS -- the unit ``min_separation`` is
    actually in (review round 2 M5).

    **THE FIRST CUT FED A MONTH COUNT TO AN INDEX RULE.** ``chain_history`` passed the band's own
    ``hi_m`` as ``min_separation``, which :func:`chain_firings` compares against ``i - kept[-1]`` --
    ARRAY INDEXES, at whatever cadence the card serves. MEASURED: a DAILY parent over a one-to-two
    quarter band (hi = 6 months) kept 83 firings where a true six-month separation keeps 3, and an
    ANNUAL parent under the same call skipped SIX YEARS between firings (5 kept where 13 fire). The
    printed figure carries its sample size ("in forty-six of fifty-nine past firings"), so the number
    the reader is handed was being distorted by the card's cadence with nothing declaring it.

    The vocabulary is the row's own: ``StateRow.recency['age_periods']`` is "age_days in the CADENCE's
    own periods", and ``feeders.CADENCE_DAYS`` is the one table that prices a period. Where the card
    declares no cadence (or declares ``release``, which has no period length) the ARRAY's own average
    spacing answers the same question from the data; where neither is available the month count stands,
    which is the shipped behaviour and the honest degenerate case."""
    m = max(0, int(months or 0))
    if not m:
        return 1
    from leviathan.graphrag.state.feeders import CADENCE_DAYS
    per = CADENCE_DAYS.get(str(getattr(st, "cadence", "") or ""))
    if not per:
        per = _array_spacing_days(dates)
    if not per:
        return max(1, m)
    return max(1, int(float(m) * _MONTH_DAYS / float(per)))


def _array_spacing_days(dates) -> Optional[float]:
    """The average calendar days between two points of a served array, or ``None``. It is the ARRAY's
    own answer to "what is one period here", used only where the card declares no cadence."""
    if len(dates or ()) < 3:
        return None
    a, b = axis_date(str(dates[0])), axis_date(str(dates[-1]))
    if not a or not b:
        return None
    try:
        import datetime as _d
        d0 = _d.date(int(a[0:4]), int(a[5:7]), int(a[8:10]))
        d1 = _d.date(int(b[0:4]), int(b[5:7]), int(b[8:10]))
    except (TypeError, ValueError):
        return None
    span = (d1 - d0).days
    return (float(span) / float(len(dates) - 1)) if span > 0 else None


def chain_firings(values, dates, *, direction: int, min_separation: int = 3,
                  asof: str = "", close_months: Optional[int] = None) -> list:
    """The PAST DATES at which this reading last entered a run in TODAY's direction.

    A FIRING IS A RUN START, which is the ``crossings``-style candidate DESIGN B.2 names: position
    ``i`` fires when the move into it has today's sign and the move before it did not. That is the
    honest reading of "the last times this reading sat here" and it is the same shape the analog
    selector's own candidate set has -- deliberately NOT imported, because `state/analogs.py` is
    another lane's file this sitting and a shared private helper across two in-flight lanes is the
    duplicate-and-drift class.

    TWO FILTERS, AND BOTH ARE THE DESIGN'S OWN HARD ONES. ``min_separation`` deduplicates ONE episode
    that stutters across three periods (the same reason the analog selector carries one), and the PIT
    rule drops a firing whose DECLARED window has not closed at the as-of -- a firing whose outcome is
    still running is not a record, it is the present. Nothing else removes a firing: a thin count is
    PRINTED, never fixed by widening the rule.

    The CURRENT run's own start is excluded by the PIT filter alone and needs no second clause: its
    window closes after the as-of by construction."""
    if direction not in (1, -1) or len(values) < 3:
        return []
    out: list = []
    prev_move = 0
    for i in range(1, len(values)):
        try:
            mv = (values[i] > values[i - 1]) - (values[i] < values[i - 1])
        except TypeError:
            mv = 0
        if mv == direction and prev_move != direction:
            out.append(i)
        if mv != 0:
            prev_move = mv
    kept: list = []
    for i in out:
        if kept and (i - kept[-1]) < max(1, int(min_separation)):
            continue
        if close_months is not None:
            closes = _add_months(str(dates[i])[:10], int(close_months))
            if not closes or (asof and closes > str(asof)[:10]):
                continue
        kept.append(i)
    return [{"index": i, "date": str(dates[i])[:10]} for i in kept]


def chain_history(parent_st, child_st, *, edge_sign: str, band: Optional[LagBand], asof: str,
                  direction: int = 0) -> dict:
    """DESIGN B.2's HISTORY term, EXECUTED over the arrays already on the board. ZERO reads.

    For the receipt hop A and the hop below it B: ``stats.sign_agreement`` over each past firing of A,
    against B's own ``stats.window_change`` over the DECLARED lag window shifted off that firing.
    Returns ``{n_firings, aligned, at_odds, undetermined, fraction, thin, words, ...}``.

    **IT GRADES, IT NEVER GATES (ruling R2, and this is the estate's own repeated failure).** There is
    no ``continue`` in this function that removes a chain, no floor under ``n`` that empties a pool,
    and the caller scores a thin record NEUTRAL rather than low. `test_state_walk`'s negative test
    pins a one-firing chain with a first-percentile receipt hop rendering in full.

    ``rolling_corr`` RIDES AS A PRINTED FACT AND NOT AS A SCORE TERM. DESIGN B.2's arithmetic is
    defined on the aligned FRACTION alone, so folding a correlation into the points would silently
    change the rank the design's own top-3 was computed under; the correlation and the percentile of
    its own history are carried beside the count so a reader gets the second number without the rank
    acquiring an undeclared term."""
    out = {"n_firings": 0, "aligned": 0, "at_odds": 0, "undetermined": 0, "unmeasured": 0,
           "fraction": 0.0, "thin": True, "words": "", "firings": (), "corr": None,
           "corr_percentile": None, "basis": "none"}
    a_vals, a_dates, _au = hop_arrays(parent_st)
    b_vals, b_dates, _bu = hop_arrays(child_st)
    if not a_vals or not b_vals or band is None or band.min_q is None:
        out["words"] = "no past firings of this reading carry a measured next hop"
        return out
    lo_m, hi_m = band.months()
    lo_m = int(lo_m or 0)
    hi_m = int(hi_m) if hi_m is not None else max(lo_m, QUARTER_MONTHS)
    if direction not in (1, -1):
        direction = _series_direction(a_vals)
    # THE SEPARATION IS IN THE ARRAY'S OWN PERIODS AND THE PIT CLOSE IS IN MONTHS. The two arguments
    # are the same band read in two units, and the first cut passed months to BOTH -- one of them into
    # an index comparison (see :func:`separation_periods`).
    firings = chain_firings(a_vals, a_dates, direction=direction,
                            min_separation=separation_periods(hi_m, parent_st, a_dates),
                            asof=asof, close_months=hi_m)
    out["basis"] = "firings"
    rows: list = []
    for f in firings:
        i = f["index"]
        try:
            parent_move = float(a_vals[i]) - float(a_vals[i - 1])
        except (TypeError, ValueError, IndexError):
            # A FIRING THE PARSE CANNOT READ IS COUNTED, NEVER SILENTLY OUT OF A PRINTED NUMBER
            # (round-2 census blocker 7, carried). `unmeasured` is a PRINTED figure -- "on any of the
            # fourteen past firings of this reading" (:func:`chain_history_words`) -- and this branch
            # dropped a firing out of BOTH counters, so the denominator a reader met was smaller than
            # the record the arrays actually held. The window drops beside it already count; this one
            # is the same fact and takes the same counter, so `n_firings + unmeasured` is every
            # firing :func:`chain_firings` returned.
            out["unmeasured"] += 1
            continue
        j0 = _at_or_after(b_dates, _add_months(f["date"], lo_m) or "")
        j1 = _at_or_before(b_dates, _add_months(f["date"], hi_m) or "")
        if j0 is None or j1 is None or j1 <= j0:
            out["unmeasured"] += 1
            continue
        # THE CALCULATOR IS HANDED THE WINDOW'S TWO ENDPOINTS, NOT THE WHOLE SERIES, and the
        # arithmetic is identical by `window_change`'s own definition (`value = series[t2] -
        # series[t1]`). `stats._floats` coerces every point of the array on every call, and the board
        # makes thousands of these calls: MEASURED at 3.6 seconds of tottime inside `_floats` on one
        # max fixture board. The WINDOW the endpoints came from is recorded on the row below, so
        # nothing about the window is lost -- only the re-coercion is.
        ch = ST.window_change([b_vals[j0], b_vals[j1]], 0, 1)
        if ch.get("declined"):
            out["unmeasured"] += 1
            continue
        verdict = ST.sign_agreement(parent_move, ch.get("value"), edge_sign).get("value")
        rows.append({"date": f["date"], "parent_move": parent_move,
                     "child_move": ch.get("value"), "verdict": verdict,
                     "child_from": str(b_dates[j0])[:10], "child_to": str(b_dates[j1])[:10]})
        out[verdict] = out.get(verdict, 0) + 1
    out["firings"] = tuple(rows)
    out["n_firings"] = len(rows)
    out["thin"] = len(rows) < CHAIN_HISTORY_THIN_N
    out["fraction"] = (out["aligned"] / len(rows)) if rows else 0.0
    if len(a_vals) >= ST.MIN_CORR_N and len(b_vals) >= ST.MIN_CORR_N:
        corr = ST.rolling_corr(list(a_vals), [str(d) for d in a_dates],
                              list(b_vals), [str(d) for d in b_dates],
                              window=ST.MIN_CORR_WINDOW,
                              label_a=(parent_st.key.label() if parent_st is not None else "a"),
                              label_b=(child_st.key.label() if child_st is not None else "b"))
        if not corr.get("declined"):
            out["corr"] = corr.get("value")
            pc = ST.percentile(corr.get("value"), corr.get("disjoint_series") or ())
            if not pc.get("declined"):
                out["corr_percentile"] = pc.get("value")
    out["words"] = chain_history_words(out)
    return out


def _series_direction(values) -> int:
    """TODAY's direction of travel on an array: the sign of the newest move, 0 when it is flat."""
    for i in range(len(values) - 1, 0, -1):
        try:
            mv = (values[i] > values[i - 1]) - (values[i] < values[i - 1])
        except TypeError:
            return 0
        if mv:
            return mv
    return 0


def chain_history_words(h: dict, *, reading: str = "", next: str = "") -> str:  # noqa: A002
    """The history line, in the past tense, with its SAMPLE SIZE -- history, never a forecast (E7) --
    and **THE TRACE TWIN OF THE PAGE'S RECORD LINE** (CONTRACT K11, the 09-24 re-smoke's items 17 and 28c).

    THE READING AND ITS NEXT LINK ARE NAMED. The record is the RECEIPT hop's own past extremes against
    the link below it, and the receipt hop is the loudest, often not the first: the deep page wrote "Of
    the past times the ratio sat this far out, eight had a next reading" for CRUDE OIL's record, because
    no line said whose record it was. ``reading`` / ``next`` are the two names (``render.chain_hop_name``
    -- the ONE printed hop name -- the far market's label, or the anchor's price, read by
    :func:`chain_score` off the chain it explains); absent, the line says "this reading" / "the next
    link", which is what it said before it could name them.

    THE WORDS ARE THE DESK'S, ONE POPULATION, TWO NUMBERS. "the past times <reading> sat this far out"
    is the population (the record line's own noun on the page, ``render.chain_record_words``); the
    MEASURED subset (``n_firings``) and the times no next reading was published inside the lag
    (``unmeasured``) are both stated, so the reader meets the trace row's own two numbers (round-4 census
    8). A thin record says so ("the record is thin") and says WHY where the reason is the next link's own
    publication cadence -- a weekly reading against an annual next link sits far out often and is never
    measured. Counts are spelled through ``render.words_for_int``, the estate's ONE cardinal producer, so
    the line mints no charged digit outside ``FIGURE_CLASSES`` (E12 / S9)."""
    from leviathan.graphrag.state.render import words_for_int
    rd = str(reading or "").strip() or "this reading"
    nx = str(next or "").strip() or "the next link"
    n = int(h.get("n_firings") or 0)
    un = int(h.get("unmeasured") or 0)
    if n < CHAIN_HISTORY_THIN_N:
        if not n and un:
            return ("the record is thin: %s sat this far out %s %s before, and on none of them was a "
                    "reading of %s published inside the lag the model allows"
                    % (rd, words_for_int(un), "time" if un == 1 else "times", nx))
        if not n:
            return ("the record is thin: it holds no past time %s sat this far out with a reading of %s "
                    "to measure" % (rd, nx))
        return ("the record is thin: only %s of the past times %s sat this far out %s a reading of %s "
                "to measure" % (words_for_int(n), rd, "has" if n == 1 else "have", nx))
    al = int(h.get("aligned") or 0)
    odds, und = h.get("at_odds"), h.get("undetermined")
    parts = ["it moved the way the model expects in %s" % words_for_int(al)]
    if odds is None and und is None:
        if n - al:
            parts.append("did not in %s" % words_for_int(n - al))
    else:
        if int(odds or 0):
            parts.append("went the other way in %s" % words_for_int(int(odds)))
        if int(und or 0):
            parts.append("settled no direction in %s" % words_for_int(int(und)))
    body = parts[0] if len(parts) == 1 else (", ".join(parts[:-1]) + " and " + parts[-1])
    tail = ("" if not un else "; %s more %s no reading of %s was published inside the lag the model "
            "allows" % (words_for_int(un), "time" if un == 1 else "times", nx))
    return ("of the past times %s sat this far out, %s had a reading of %s to measure: %s%s"
            % (rd, words_for_int(n), nx, body, tail))


def chain_record_names(ch) -> tuple:
    """``(reading, next)`` -- the two names the record line owes its reader (CONTRACT K11's trace twin):
    the RECEIPT hop by ``render.chain_hop_name`` (the ONE printed hop name, never a routing id), and the
    link below it -- the next hop by the same producer, the far market by its board label where the
    receipt hop is the last one and a cross was earned, the anchor's own price otherwise."""
    if not getattr(ch, "hops", None):
        return ("", "")
    try:
        from leviathan.graphrag.state.render import board_label, chain_hop_name
    except Exception:                                   # noqa: BLE001 -- a name is never worth a turn
        return ("", "")
    i = int(getattr(ch, "receipt_index", 0) or 0)
    i = i if 0 <= i < len(ch.hops) else 0
    reading = chain_hop_name(ch.hops[i])
    if i + 1 < len(ch.hops):
        nxt = chain_hop_name(ch.hops[i + 1])
    elif getattr(ch, "cross", None):
        nxt = board_label(ch.terminal or ch.contract)
    else:
        nxt = "the %s price" % board_label(ch.contract)
    return (reading, nxt)


# ── the outcome line: the base rate a PM pays for ────────────────────────────────────────────────────
def chain_outcome(price_values, price_dates, *, unit: str, firings, band: Optional[LagBand],
                  declared_sign: str = "", scope: str = "") -> dict:
    """What the ANCHOR's own price did after each past firing -- ``{n, median_move, range,
    share_declared_way, words}``, in the PAST TENSE, as history and never as a forecast.

    **IT IS SCOPED BY THE ARRAY IT HAS, AND THE SENTENCE SAYS SO.** MEASURED on the S8 recon: the
    anchor's front-month tape is ~320 sessions by DECLARATION (`feeders.py:1610-1648` -- two windows
    plus a roll margin, worst-case span 478 calendar days), ``bd.tape`` is keyed by ANCHOR SLUG only
    so no far market has a tape at all, and ``board_map``'s 47 refs declare NO level price series. So
    an outcome line over a firing older than about eighteen months is NOT CONSTRUCTIBLE at zero reads,
    and the honest forms are (a) the window the array actually covers, named in the sentence, or (b)
    "no price history over these firings". Both are here; neither is a new read, and NEITHER REMOVES
    THE CHAIN -- the chain renders with the line that says what it could not price.

    ONE CALCULATOR: the median and the range come from ``stats.quantiles``. When the sample is under
    that module's own floor the line REFUSES THE MEDIAN and prints the count and the share instead --
    a count is not a distribution and must not be dressed as one."""
    out = {"n": 0, "n_in": len(list(firings or ())), "median_move": None, "low": None, "high": None,
           "share_declared_way": 0, "unit": "percent", "scope": scope,
           # THE WINDOW'S TWO DATES AS FIELDS AND NOT ONLY AS PROSE (lane R's handoff W-R5). The page's
           # call record needs the period (`<from>..<to>`) and the vintage, and it read them back out
           # of `scope`'s sentence with a regex; the sentence is the reader's, these two are the
           # machine's, and one producer mints both so they cannot disagree.
           "window_from": (str(price_dates[0])[:10] if price_dates else ""),
           "window_to": (str(price_dates[-1])[:10] if price_dates else ""),
           "words": "no price history over the past times this reading sat this far out",
           "moves": ()}
    if not price_values or not firings or band is None or band.min_q is None:
        return out
    lo_m, hi_m = band.months()
    lo_m = int(lo_m or 0)
    hi_m = int(hi_m) if hi_m is not None else max(lo_m, QUARTER_MONTHS)
    moves: list = []
    for f in firings:
        j0 = _at_or_after(price_dates, _add_months(f["date"], lo_m) or "")
        j1 = _at_or_before(price_dates, _add_months(f["date"], hi_m) or "")
        if j0 is None or j1 is None or j1 <= j0:
            continue
        ch = ST.window_change([price_values[j0], price_values[j1]], 0, 1)
        if ch.get("declined") or ch.get("pct_change") is None:
            continue
        moves.append(float(ch["pct_change"]))
    if not moves:
        return out
    want = _SIGN_INT.get(str(declared_sign or ""))
    out["moves"] = tuple(moves)
    out["n"] = len(moves)
    out["share_declared_way"] = (0 if want is None else
                                 sum(1 for m in moves if (m > 0) - (m < 0) == want))
    q = ST.quantiles(moves, (0.0, 0.5, 1.0))
    if not q.get("declined"):
        out["median_move"] = q["quantiles"]["0.5"]
        out["low"], out["high"] = q["quantiles"]["0"], q["quantiles"]["1"]
    out["words"] = chain_outcome_words(out, declared_sign=declared_sign)
    return out


def chain_outcome_words(o: dict, *, declared_sign: str = "") -> str:
    """The outcome sentence. PAST TENSE, with its sample size and the window it was read over.

    **ONE NOUN FOR THE PAST FIRINGS OF THIS READING, ONE COUNT, AND ITS EXPLAINED SUBSET** (review
    MA-5). ``chain_history_words`` prints "in eleven of FOURTEEN past firings of this reading ..." and
    this line used to open "after FIVE past firings of this reading ...", where the five is the subset
    of the fourteen that the anchor's own price array could reach -- and NOTHING in either sentence
    said it was a subset. MEASURED on the deep fixture's rendered chain: history ``n_firings`` 14,
    outcome ``n`` 5. The page was saved there only because five sits under ``stats.quantiles``' own
    floor, so the median was refused; on a board whose tape reaches one more firing the block carries
    two counts of one population under one noun. This is the law S7b applied to the board -- one
    series, counted ONCE, in ONE spelling -- so the count line here is the SUBSET and it says so.

    AND THE "over" CLAUSE IS SAID ONCE (lane R's handoff W-R7): the template carried "over the declared
    window" and then appended ``" over %s" % scope``, whose own sentence opens "the front price's own
    ...", so the trace read "over the declared window over the front price's own ... window"."""
    from leviathan.graphrag.state.render import words_for_int
    n = int(o.get("n") or 0)
    n_in = int(o.get("n_in") or 0)
    if not n:
        return "no price history over the past times this reading sat this far out"
    # THE SUBSET AND ITS DENOMINATOR, IN ONE CLAUSE AND IN THE RECORD LINE'S OWN NOUN -- the desk's
    # "past times this reading sat this far out", never the instrument's "firings" (the 09-24 fix round,
    # item 28c: the trace twin of the page's `render._firings_read_words`, one noun on both surfaces).
    head = ("%s of the %s past %s this reading sat this far out %s a price reading over the band"
            % (words_for_int(n), words_for_int(n_in), "time" if n_in == 1 else "times",
               "carries" if n == 1 else "carry")
            if n_in > 0 else
            "%s past %s this reading sat this far out %s a price reading over the band"
            % (words_for_int(n), "time" if n == 1 else "times",
               "carries" if n == 1 else "carry"))
    scope = (", read over %s" % o["scope"]) if o.get("scope") else ""
    way = ""
    if declared_sign and o.get("share_declared_way") is not None:
        way = ", %s of them the declared way" % words_for_int(int(o["share_declared_way"]))
    if o.get("median_move") is None:
        return ("%s%s%s; the sample is too thin for a middle figure" % (head, way, scope))
    return ("%s; the front price moved a middle %.1f percent over the band%s%s (the range "
            "ran %.1f percent to %.1f percent)"
            % (head, float(o["median_move"]), scope, way,
               float(o.get("low") or 0.0), float(o.get("high") or 0.0)))


# ── the curated prior ────────────────────────────────────────────────────────────────────────────────
def curated_chain_index(chains) -> dict:
    """THE ADAPTER for the estate's ten curated chains and two transmission chains.

    **THE TWO CONFIGS DISAGREE WITH `chain_paths` ON TWO AXES AND THE JOIN MUST BE DECLARED.**
    ``cascade.load_chain_map()`` returns ``{id, contracts:[slug], hops:[{node, ref, country?}],
    terminal}`` -- DRIVER NODES, keyed by contract. ``cascade.load_transmission_map()`` returns
    ``{id, links:[{pair_id, source, target, nature}]}`` -- MARKET to MARKET. And `chain_paths` reads
    ``ch['name']`` and then ``h in loud`` where its ``loud`` is a set of BOARD SLUGS and ``h`` would be
    a dict -- ``TypeError: unhashable type: 'dict'`` on the first row, which is why the curated rows
    have reached no turn (`notes[kind=chains].rows == ()` on 5 of 5 banked payloads).

    So this function declares the axis instead of guessing it. It returns
    ``{"nodes": {contract: [(id, (node, ...)), ...]}, "markets": {(source, target): id}}`` -- the node
    axis for the DRIVER hops a composed chain is made of, and the market axis for the ONE cross hop a
    composed chain can carry. A curated row NEVER mints a chain and never removes one: it is a PRIOR,
    worth the CONFIDENCE term at its maximum and the curated name on the page."""
    out: dict = {"nodes": {}, "markets": {}}
    for ch in (chains or ()):
        if not isinstance(ch, dict):
            continue
        cid = str(ch.get("id") or ch.get("name") or "")
        if not cid:
            continue
        hops = ch.get("hops") or ()
        nodes = tuple(str((h or {}).get("node") if isinstance(h, dict) else h or "") for h in hops)
        nodes = tuple(n for n in nodes if n)
        if nodes:
            for slug in (ch.get("contracts") or ()):
                out["nodes"].setdefault(str(slug), []).append((cid, nodes))
        for lk in (ch.get("links") or ()):
            if not isinstance(lk, dict):
                continue
            src, tgt = str(lk.get("source") or ""), str(lk.get("target") or "")
            if src and tgt:
                out["markets"].setdefault((src, tgt), cid)
                out["markets"].setdefault((tgt, src), cid)
    return out


def _curated_for(index: dict, contract: str, hop_ids: tuple, cross_other: str = "") -> str:
    """The curated id whose hop sequence this composed chain CONTAINS, in order, or ``''``.

    ORDERED SUBSEQUENCE rather than contiguity, because the curated rows skip hops the DAG declares
    (``safrinha -> ending_stocks_su_ratio`` is one curated step over a real DAG edge) and a contiguity
    test would refuse the very rows the prior exists to honour."""
    for cid, nodes in (index.get("nodes", {}).get(contract) or ()):
        it = iter(hop_ids)
        if all(any(h == n for h in it) for n in nodes):
            return cid
    if cross_other:
        return index.get("markets", {}).get((contract, cross_other), "") or ""
    return ""


# ── the rank ─────────────────────────────────────────────────────────────────────────────────────────
def registry_buffer_refs() -> frozenset:
    """THE CARD REGISTRY'S OWN BALANCE / BUFFER / PACE REFS (owner ruling 6b, 2026-09-18).

    ``verify.BAR_FAMILY_REFS['level_decile']`` plus every series the desk-convention registry declares
    with ``percentile_bands`` (a TAIL CUT on the series' own history -- which is what a buffer IS) or
    ``pace_vs_prior_year`` (an export pace against its own prior year), MINUS the POSITIONING refs,
    which are a different family with their own term below. Read from the two registries the estate
    already keeps per series, never re-typed here: a market's buffer is whatever its cards declare.

    A MARKET WITH NO SUCH SERIES ON ITS BOARD SCORES ZERO ON THAT TERM AND THE SENTENCE SAYS SO. A firm
    does not have equal data on every contract, and the page says what it had."""
    refs: set = set()
    try:
        from leviathan.graphrag import verify as _V
        refs |= {str(r) for r in (_V.BAR_FAMILY_REFS.get("level_decile") or ())}
        pos = {str(r) for r in (_V.BAR_FAMILY_REFS.get("positioning") or ())}
    except Exception:                                   # noqa: BLE001 -- a registry read never kills a turn
        pos = set()
    try:
        from leviathan.graphrag.state.lint import load_conventions
        for ref, row in ((load_conventions() or {}).get("conventions") or {}).items():
            if str((row or {}).get("kind") or "") in ("percentile_bands", "pace_vs_prior_year"):
                refs.add(str(ref))
    except Exception:                                   # noqa: BLE001
        pass
    return frozenset(refs - pos)


def positioning_refs() -> frozenset:
    """The POSITIONING family, from the estate's own register (``verify.BAR_FAMILY_REFS``)."""
    try:
        from leviathan.graphrag import verify as _V
        return frozenset(str(r) for r in (_V.BAR_FAMILY_REFS.get("positioning") or ()))
    except Exception:                                   # noqa: BLE001
        return frozenset({"cot_mm_positioning"})


def anchor_facts(bd: B.Board, contract: str) -> AnchorFacts:
    """:class:`AnchorFacts` for ONE anchor board, at zero reads. Called once per contract by
    :func:`chain_rows` and read by every candidate chain on that contract.

    **THE PRICE ROW IS READ OFF ``bd.tape`` AND THE TAPE MUST BE ATTACHED BEFORE THE CHAIN LEG
    COMPOSES** (owner ruling 2, and the round-2 census's blocker 3). This function is the ONE reader of
    the anchor's own front price for the chain's TAIL term, and it reads the tape THE BOARD HAS: with
    the tape attached first, the fixture's soybean price sits at the 83rd percentile of its own record
    and ``price_tail`` is 0.6656, and chains whose hops are quieter than that score TAIL on the
    terminal and stamp ``Chain.scope['price_read']``. MEASURED on the same fixture with the tape
    attached AFTER stage 2 -- which is the order ``seam.fill_stage2`` shipped -- ``bd.tape`` is EMPTY
    when this runs, ``price_tail`` is 0.0000 on every chain of every tier, and an owner-ordered term is
    unreachable by construction rather than by measurement. The ORDERING is the seam's (lane R moves
    ``_attach_tape`` above the chain composition); what this function owes is to read the tape when it
    is there, to stamp the fact, and to say so here so the ordering is never rediscovered."""
    bufs = registry_buffer_refs()
    pos_refs = positioning_refs()
    buffer_ids: set = set()
    pos_id, pos_pct = "", None
    events = False
    for r in bd.rows_for(contract):
        ref = str(r.silver_ref or "")
        st = r.state
        ok = st is not None and status_word(st.status) == "ok"
        if ref in bufs or r.driver_id in bufs:
            buffer_ids.add(r.driver_id)
        if (ref in pos_refs or r.driver_id in pos_refs) and ok and not pos_id:
            pos_id, pos_pct = r.driver_id, _measure_value(st.percentile)
        if r.event_date or r.event_receipt or (r.receipts or {}).get("top"):
            events = True
    tp = (bd.tape or {}).get(contract)
    ppct = _measure_value(getattr(tp, "percentile", None)) if tp is not None else None
    return AnchorFacts(contract=contract, buffer_ids=frozenset(buffer_ids),
                       buffer_served=bool(buffer_ids), positioning_id=pos_id,
                       positioning_percentile=pos_pct,
                       price_tail=_hop_tail(ppct, None), price_percentile=ppct,
                       price_window=str(getattr(tp, "window_note", "") or ""),
                       events_served=events)


def _is_buffer(hop: ChainHop, anchor: Optional[AnchorFacts]) -> bool:
    """Is this hop a BUFFER of its own market? The card registry answers where a board was threaded;
    the design's literal token list answers the offline harness, and the difference is declared."""
    if anchor is not None:
        return hop.driver_id in anchor.buffer_ids
    return any(t in hop.driver_id for t in CHAIN_BUFFER_TOKENS)


def _positioning_facts(ch: Chain, anchor: Optional[AnchorFacts]) -> dict:
    """``Chain.positioning`` -- WHERE THE CROWD IS AND WHICH WAY -- or ``{}`` (owner ruling 1).

    ONE PRODUCER FOR THE FACT AND THE POINTS. :func:`_positioning_note` scores and spells this dict and
    the page prints it (``render.sb_chain_positioning``), so the row a reader meets and the points the
    rank spent can never describe two different crowds. It is EMPTY unless the clause actually fires --
    a positioning row at the 50th percentile is not a crowd, and a row printed as one would be a claim
    the arithmetic never made.

    ``key`` IS THE PAIR AND NEVER THE ID (E11): ``cot_mm_positioning`` is a row of every futures board
    this turn carries, so the page looks the standing's address up on ``(contract, driver_id)`` and
    prints its handle only where THIS page carries that row."""
    if anchor is None or anchor.positioning_percentile is None or not anchor.positioning_id:
        return {}
    p = float(anchor.positioning_percentile)
    if not (p >= CHAIN_CROWDED_HIGH or p <= CHAIN_CROWDED_LOW):
        return {}
    if ch.direction not in ("higher", "lower"):
        return {}
    crowded = "higher" if p >= CHAIN_CROWDED_HIGH else "lower"
    return {"percentile": p, "against": bool(ch.direction != crowded),
            "key": (str(anchor.contract), str(anchor.positioning_id))}


def _positioning_note(ch: Chain, anchor: Optional[AnchorFacts], with_notes: bool = True) -> tuple:
    """``(points, sentence)`` for the POSITIONING clause of ASYMMETRY (owner ruling 1, 2026-09-18).

    **THE RULE AS THE OWNER'S OWN PARENTHETICAL AND PRINTED CLAUSE STATE IT**: a managed-money net at
    or past the 90th / 10th percentile of its own record, CROWDED THE SAME WAY THE CHAIN ARGUES ("a
    crowded long on a chain that argues higher prices, or the mirror"), earns the credit and prints
    "positioning is crowded the same way, which makes the reversal abrupt" -- the smoke's own PM read
    flagged twice that a 100th-percentile long into a bullish call is the risk that kills the position.
    A crowded position the OTHER way is printed as the cushion it is and scores nothing.

    It is a RANK TERM AND NEVER A FILTER, it is capped inside the ten ASYMMETRY points, and a market
    whose board carries no positioning row simply does not reach this clause."""
    facts = _positioning_facts(ch, anchor)
    if not facts:
        return (0.0, "")
    p = float(facts["percentile"])
    same = not bool(facts["against"])
    if not with_notes:
        # THE SENTENCES ARE DEFERRED TO THE CHAINS A READER MEETS (`chain_score`'s own rule): a board
        # composes up to 1,848 candidates and building this one for every one of them is prose nobody
        # reads. The POINTS are always computed -- the rank is never a sample.
        return ((CHAIN_POSITIONING_POINTS if same else 0.0), "")
    pct = "%d%s percentile" % (int(round(p)), _pct_suffix(int(round(p))))
    if same:
        return (CHAIN_POSITIONING_POINTS,
                "positioning is crowded the same way (%s at the %s of its own record), which makes "
                "the reversal abrupt" % (_words(anchor.positioning_id), pct))
    return (0.0, "positioning is crowded the other way (%s at the %s of its own record), which "
                 "cushions this one" % (_words(anchor.positioning_id), pct))


def _words(node_id: str) -> str:
    """A driver id as READER WORDS through the estate's ONE display vocabulary (`render.humanise`).

    IT IS NOT A CONVENIENCE HERE EITHER (review round 2 M1). Every sentence this module builds reaches
    a trace the arm reads and, wherever a later lane prints one, a page -- and a raw driver id or a raw
    contract slug in reader prose is `register.internal_leaks`' never-relaxable class, which
    `Block.add` answers by REPLACING the line and dropping its citations. MEASURED before this landed:
    six of sixty rendered-chain sentences tripped the block's own fence, one per rendered chain on
    every tier. One vocabulary, one producer, and `sb_path` is the precedent."""
    from leviathan.graphrag.state.render import humanise
    return humanise(node_id)


def _market_label(slug: str) -> str:
    """A CONTRACT slug as reader words (`render.board_label`) -- the same producer `sb_path` uses."""
    from leviathan.graphrag.state.render import board_label
    return board_label(slug)


def _term_points(terms: dict, term: str) -> float:
    """ONE rank term's points, coerced exactly as ``render.chain_arithmetic_words`` coerces them.

    It exists so ``Chain.scope["terms_scored"]`` and the pairs the page enumerates are ONE arithmetic
    over one dict and can never drift into two numbers under one word (lane R's handoff R3-W1)."""
    try:
        return float(terms.get(term) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _term_was_read(term: str, terms: dict, *, n_firings: int, kind: str,
                   horizon_months: Optional[int], band: Optional[LagBand]) -> bool:
    """DID THIS TERM HAVE ANYTHING TO READ? -- the ONE rule behind ``Chain.scope['terms_read']``.

    FIVE OF THE SEVEN TERMS ANSWER WITH THEIR OWN POINTS: a term that scored above zero read
    something by construction. The two that do not are the ones that carry a NEUTRAL:

      * HISTORY scores :data:`CHAIN_HISTORY_NEUTRAL` exactly when ``n_firings == 0`` -- no record at
        all -- so points above zero there mean the opposite of "read";
      * LAG scores 1 when no horizon was asked or the top hop declares no band, which is the same
        neutral one step over. A horizon that was asked and sits OUTSIDE the declared window scores
        ZERO and it DID read: the window was there and the question's horizon missed it, which is a
        reading and is counted.

    EVENT is stated explicitly rather than left to its points, because "no dated document" and
    "a document scoring zero" must never become the same fact here (:data:`CHAIN_EVENT_POINTS` gives
    ``none`` zero today, and a later weight change must not silently move this count)."""
    if term == "history":
        return int(n_firings or 0) > 0
    if term == "lag":
        return horizon_months is not None and band is not None and band.min_q is not None
    if term == "event":
        return str(kind or "none") != "none"
    try:
        return float(terms.get(term) or 0.0) > 0.0
    except (TypeError, ValueError):
        return False


def chain_score(ch: Chain, *, named_markets=(), horizon_months: Optional[int] = None,
                history: Optional[dict] = None, with_notes: bool = True,
                anchor: Optional[AnchorFacts] = None) -> Chain:
    """DESIGN B.2's 100 points, each one PRINTABLE, computed on what the board already holds.

    Nothing here removes a chain. Every term is a WEIGHT: an unmeasured receipt hop scores ``tail
    0/25`` and the arithmetic line says so, a thin record scores the neutral 7.5 and the words say so,
    and an unearned cross hop costs the chain its five REACH points and nothing else.

    ``with_notes`` BUILDS THE SENTENCES, and it is False on the pool for a measured reason: a board
    composes hundreds to a couple of thousand candidate chains (MEASURED on the fixture: 180 quick,
    1,280 deep, 1,848 max) and a reader meets one to three of them. Building seven printable sentences
    for every candidate cost 2.5 seconds of a board whose whole stage 2 is 108 ms. The ARITHMETIC is
    always computed -- the rank is never a sample -- and :func:`chain_explain` fills the sentences for
    the few chains that reach a page or a payload."""
    hops = ch.hops
    named = set(named_markets or ())
    terms: dict = {}
    notes: dict = dict(ch.notes) if not with_notes else {}

    # TAIL 25 -- and the loudest hop by this measure IS the chain's receipt hop.
    order = _tail_order(hops)
    best = chain_receipt_index(hops)
    ch.receipt_index = best
    rh = hops[best] if hops else None
    measure = (rh.chain_tail if rh is not None else 0.0)
    # THE ANCHOR'S OWN PRICE ROW IS A READING ON THIS CHAIN'S TERMINAL (owner ruling 2, 2026-09-18).
    # Where no cross was earned the chain lands on the anchor's own front price, so a chain that
    # terminates on a price sitting at the 95th percentile of its own record scores TAIL on the
    # terminal as well as on the hops. The richer price standing -- the front spread, the curve,
    # realised volatility -- is the docketed PRICE STANDING v2 lane and the sentence says so.
    price_used = bool(anchor is not None and not ch.cross and anchor.price_tail > measure)
    if price_used:
        measure = float(anchor.price_tail)
    terms["tail"] = round(CHAIN_TERM_MAX["tail"] * measure, 1)
    if not with_notes:
        pass
    elif price_used:
        notes["tail"] = (
            "%s sits at the %d%s percentile of its own record; the wider price standing -- the front "
            "spread, the curve, realised volatility -- is not served on this page"
            % (_market_label(ch.contract), int(round(float(anchor.price_percentile or 0.0))),
               _pct_suffix(int(round(float(anchor.price_percentile or 0.0))))))
    elif rh is None or not rh.measured:
        notes["tail"] = ("no series is served for this hop; its declared direction is carried alone")
    else:
        notes["tail"] = _tail_words(rh)

    # REACH 25 -- non-obviousness is a POSITIVE weight (ruling R2), never a penalty.
    # **N8, RESTORED TO THE BANKED ARITHMETIC (2026-09-25, after measurement).** The day's first N8 ruling
    # split the ten points for an unnamed terminal into five for reaching it and five more only where its
    # own move is readable. MEASURED on the ten 09-25 traces (`rw2_reach_split_drive`): 0 of the 91 carried
    # chains ending on an unnamed market had a READ terminal -- the walk reads a far board only for a named
    # or anchored market, so every one is `undetermined` -- the readable half never fired, and the split was
    # only a five-point cut on every depth-2 unnamed chain (79 rows) that moved four lead seats onto DEEPER
    # chains which also end on unread markets. OWNER RULING 2026-09-25: CROSS-MARKET CHAINS AND FAR MARKETS
    # ARE NEVER DEMOTED OR DROPPED FOR LACK OF DATA -- the reach credit for an unnamed terminal is whole; when
    # far-market reads land (the curve lane: the terminal price and the far board's same-driver row), a READ
    # terminal may earn extra credit and an unread one never loses any. So the points are HEAD 21b111c7's
    # exactly: 10 [depth >= 2] + 5 [depth >= 3] + 10 [unnamed terminal] + 5 [earned cross], capped at
    # ``CHAIN_TERM_MAX["reach"]``. WHAT STAYS OF THE SPLIT IS WORDS: the reach note says whether this record
    # reads the far market's own move, through the ONE predicate :func:`terminal_read` that :func:`_agree`
    # reads for the verdict's child move (over `Chain.terminal_reading`, stamped by `_agree` BEFORE this
    # score runs in both :func:`_compose` and :func:`_with_cross`) -- it informs the reader and moves no
    # point, which is why it is read only where the note is built. The rejected lexical form: a list of
    # foreign boards or exchanges.
    reach = 0
    if ch.depth >= 2:
        reach += 10
    if ch.depth >= 3:
        reach += 5
    ch.unnamed_terminal = bool(ch.terminal) and ch.terminal not in named
    if ch.unnamed_terminal:
        reach += 10
    if ch.cross:
        reach += 5
    terms["reach"] = min(reach, int(CHAIN_TERM_MAX["reach"]))
    if with_notes:
        far_move_read = bool(ch.unnamed_terminal) and terminal_read(ch.terminal_reading)
        notes["reach"] = ("depth %d, reaching %s" % (
            ch.depth, _market_label(ch.terminal or ch.contract))) + (
            ((", a market this question did not name, whose own move this record reads"
              if far_move_read else
              ", a market this question did not name, whose own move this record cannot read"))
            if ch.unnamed_terminal else "")

    # EVENT 20 -- the order of choice of DESIGN B.4, at the RECEIPT hop first and then along the chain.
    if ch.receipt_kind == "none" and ch.receipt is None and not ch.receipt_words:
        kind, receipt, words, aged, aged_hop, aged_date = _chain_receipt(ch)
        ch.receipt_kind, ch.receipt, ch.receipt_words = kind, receipt, words
        ch.receipts_aged_out = int(aged)
        ch.aged_receipt_hop, ch.aged_receipt_date = aged_hop, aged_date
    else:
        kind, words = ch.receipt_kind, ch.receipt_words
    terms["event"] = CHAIN_EVENT_POINTS.get(kind, 0)
    if with_notes:
        # A MARKET WITH NO DATED DOCUMENT AT ALL PRINTS THAT, NEVER A SILENT ZERO (owner ruling 6).
        # "nothing in this hop's window" and "nothing on this market reached this turn" are different
        # facts about a term that scored the same, and the reader is owed the one that is true.
        notes["event"] = (words or (
            "no dated document about this market reached this turn, so no chain on it can carry one"
            if (anchor is not None and not anchor.events_served) else
            "no dated document in this hop's window among the documents this turn retrieved"))

    # HISTORY 15 -- a weight and a printed number with its sample size. NEVER a gate (E9).
    h = dict(history or {})
    ch.history = h
    n = int(h.get("n_firings") or 0)
    frac = float(h.get("fraction") or 0.0)
    if n >= CHAIN_HISTORY_FULL_N:
        terms["history"] = round(CHAIN_TERM_MAX["history"] * frac, 1)
    elif n >= CHAIN_HISTORY_THIN_N:
        terms["history"] = round(CHAIN_TERM_MAX["history"] * frac * CHAIN_HISTORY_DISCOUNT, 1)
    else:
        terms["history"] = CHAIN_HISTORY_NEUTRAL
    if with_notes:
        # THE RECORD NAMES ITS READING AND ITS NEXT LINK (K11's trace twin, item 28c): the words are
        # re-stated with the two names on this chain's own copy of the record (`h` is a copy), so the
        # trace's `history.words` and `notes.history` are one sentence.
        _rd, _nx = chain_record_names(ch)
        h["words"] = chain_history_words(h or {"n_firings": 0}, reading=_rd, next=_nx)
        notes["history"] = h["words"]

    # ASYMMETRY 10 -- a thin buffer, a line within reach, a run near its own record, and POSITIONING.
    asym, anote = 0.0, ""
    for i in order:
        hp = hops[i]
        if hp.percentile is None:
            continue
        p = float(hp.percentile)
        # A HOP WHOSE PHASE IS NOT THE ONE IN FORCE IS AT A TAIL ONLY ON ITS OWN POLE (W-7): a La Nina
        # hop reading ONI at the 95th percentile is the warm pole's tail, not its own.
        if not _at_own_tail(hp, p):
            continue
        buf = _is_buffer(hp, anchor)
        asym = 10.0 if buf else 5.0
        if with_notes:
            anote = "%s at the %d%s percentile of its own record" % (
                _words(hp.driver_id), int(round(p)), _pct_suffix(int(round(p))))
        break
    if not asym:
        for i in order:
            # ...and the desk line a re-oriented hop's reading sits on is the OTHER pole's line.
            if hops[i].convention_label and not hops[i].phase_reoriented:
                asym = 10.0
                if with_notes:
                    anote = "%s sits on a declared desk line (%s)" % (
                        _words(hops[i].driver_id), hops[i].convention_label)
                break
    # POSITIONING AS ASYMMETRY (owner ruling 1, 2026-09-18) -- a rank term, printed, inside the ten.
    # THE FACT IS STAMPED ON EVERY CANDIDATE, NOT ONLY ON THE ONES THAT GET SENTENCES: the points are
    # always computed (the rank is never a sample) and the page's positioning row reads this dict, so
    # deferring it with the prose would have made the row absent on every chain a reader ever meets.
    ch.positioning = _positioning_facts(ch, anchor)
    pos_pts, pos_note = _positioning_note(ch, anchor, with_notes)
    terms["asymmetry"] = round(min(float(CHAIN_TERM_MAX["asymmetry"]), asym + pos_pts), 1)
    if getattr(ch, "premise_off", False):
        # A PREMISE NOT IN FORCE EARNS NO ASYMMETRY CREDIT (CONTRACT K13): the chain's own first link is
        # the phase the reading does not put in force, so a tail further down it is not this chain's
        # convexity -- MEASURED, max chain 3 (corn / La_Nina at ONI +1.8) took 10 of 10 here off a
        # positioning row at the 99.7th percentile. The term reads zero and says why; the rank sees it.
        terms["asymmetry"] = 0.0
        if with_notes:
            anote = ("the chain's first link is the phase the reading does not put in force, so no "
                     "reading on it earns the asymmetry credit")
            pos_note = ""
    if with_notes:
        # THE ABSENCE NAMES ITSELF (owner ruling 6b): a market that serves NO buffer series scores
        # zero here for a reason a reader can check, and never reads as a chain that failed a test.
        base = anote or ("no buffer series is served for this market, so no reading on this chain "
                         "can sit at a buffer's own tail"
                         if (anchor is not None and not anchor.buffer_served) else
                         "no reading on this chain sits at a tail of its own record")
        notes["asymmetry"] = ("%s; %s" % (base, pos_note)) if pos_note else base

    # CONFIDENCE 3 -- the WEAKEST hop bounds the chain (today's `path_rank` law, kept). A curated
    # chain takes the term at its maximum: a human ratified the sequence, which is the strongest
    # confidence statement the estate can make about a path.
    confs = [CONFIDENCE_RANK.get(h_.confidence, 1) for h_ in hops]
    if ch.curated:
        terms["confidence"] = CHAIN_TERM_MAX["confidence"]
        if with_notes:
            notes["confidence"] = "a curated chain of the estate's own map (%s)" % _words(ch.curated)
    else:
        terms["confidence"] = (round(CHAIN_TERM_MAX["confidence"] * (min(confs) / 2.0), 1)
                               if confs else 1.5)
        if with_notes:
            notes["confidence"] = "the weakest declared link on it is %s" % (
                min(hops, key=lambda x: CONFIDENCE_RANK.get(x.confidence, 1)).confidence if hops
                else "medium")

    # LAG FIT 2 -- never negative, never a gate.
    _lag, _lagnote = _chain_lag_fit(ch, horizon_months)
    terms["lag"] = _lag
    if with_notes:
        notes["lag"] = _lagnote

    ch.terms = terms
    ch.notes = notes
    # THE DATA SCOPE THE ARITHMETIC LINE STATES (owner ruling 6a, 2026-09-18). The rank is RELATIVE
    # WITHIN ONE BOARD, so a low score must read as scarce data and never as a bad chain: the page
    # says how many of the seven terms had anything to read, how many hops served no series, whether
    # this market serves a buffer family at all, and whether any dated document reached the turn.
    #
    # **A TERM IS "READ" WHERE IT READ SOMETHING, NEVER WHERE IT MERELY SCORED** (review MA-3). The
    # first cut counted every term with points above zero, and TWO of the seven carry a NEUTRAL: HISTORY
    # scores 7.5 exactly when there is NO record (a chain nobody has a record for must not rank below a
    # chain with a BAD one -- correct for the rank), and LAG scores 1 when no horizon was asked. So the
    # deep fixture's first rendered chain printed "six of seven terms scored" one line above "history
    # thin: the next hop publishes no second reading ... on any of the fourteen past firings", and the
    # instrument ruling 6(a) added so a low score would read as SCARCE DATA was counting the scarcity
    # as a reading. The arithmetic is the same arithmetic, read off the facts already on the object,
    # and it is published under its own name (`terms_read`) rather than under the page's.
    #
    # **AND `terms_scored` IS THE NUMBER THE PAGE PRINTS, WITH THE READ COUNT BESIDE IT UNDER ITS OWN
    # NAME** (lane R's handoff R3-W1, orchestrator ruling 2026-09-22). `render.chain_arithmetic_words`
    # counts the PAIRS it enumerates -- every term with points above zero -- and this dict published
    # `_term_was_read`'s SEMANTIC count under the same word, so one sentence ("six of seven terms
    # scored") had two numbers: MEASURED across the three fixture tiers, 5 of 6 rendered chains
    # disagreed, always low, and the trace, the arm report and the judge read the one the reader never
    # saw. ONE NAME, ONE NUMBER: `terms_scored` is the page's own count, computed HERE, after every
    # term including HISTORY is set, so the two cannot drift; `terms_read` carries MA-3's fact -- how
    # many terms had anything to READ, with the two NEUTRALS (history with no record, lag with no
    # horizon) excluded -- which is the instrument ruling 6(a) asked for and it is not deleted, only
    # named. A fence CORRECTS or COMPUTES.
    ch.scope = {"terms_total": len(CHAIN_TERMS),
                "terms_scored": sum(1 for t in CHAIN_TERMS if _term_points(terms, t) > 0.0),
                "terms_read": sum(1 for t in CHAIN_TERMS
                                  if _term_was_read(t, terms, n_firings=n, kind=ch.receipt_kind,
                                                    horizon_months=horizon_months,
                                                    band=(hops[0].lag_band if hops else None))),
                "hops": len(hops), "hops_no_series": sum(1 for h in hops if not h.measured),
                # THE TWO KEYS THE PAGE READS ARE THE PAGE'S OWN SPELLING (`CHAIN_SEAM_FIELDS`):
                # `render.chain_arithmetic_words` asks "does this MARKET serve any buffer series at
                # all" and "did this turn retrieve any dated action for it", which is what these two
                # answer. One spelling, published, pinned against the shipped object.
                "buffer_series": (None if anchor is None else bool(anchor.buffer_served)),
                "events_in_corpus": (None if anchor is None else bool(anchor.events_served)),
                "price_read": bool(price_used),
                "price_standing": ("level and its own window percentile" if price_used else "")}
    ch.score = round(sum(float(terms[t]) for t in CHAIN_TERMS), 1)
    return ch


def _at_own_tail(hp: ChainHop, p: float) -> bool:
    """IS A PERCENTILE AT THIS HOP'S OWN TAIL? -- HEAD's 90 / 10 cuts for every hop, and ONE of them for
    a hop scored on its own pole (:attr:`ChainHop.phase_reoriented`): the pole's own side of the
    record, never the other pole's."""
    if getattr(hp, "phase_reoriented", False):
        return p <= 10.0 if int(getattr(hp, "phase_orient", 0) or 0) < 0 else p >= 90.0
    return p >= 90.0 or p <= 10.0


def _tail_words(rh: ChainHop) -> str:
    """The TAIL sentence for a measured receipt hop -- BOTH the window peak and the latest reading
    (owner ruling 5, 2026-09-18), because a peak printed alone wears today's date to every reader.

    "peaked at the 97th percentile in June 2026 and reads the 80th now; the declared lag runs to
    November 2026" is the shape the ruling states in words. Where the loudest reading in the window IS
    the latest one, the sentence is the single-reading one it always was."""
    has_pct = rh.percentile is not None
    latest = ("the %d%s percentile of its own record"
              % (int(round(rh.percentile)), _pct_suffix(int(round(rh.percentile))))
              if has_pct else "%.2f sigma from its own middle" % float(rh.z or 0.0))
    # THE READING IS NAMED BY THE ONE PRINTED HOP NAME AND THE VERB IS THE EXTREME'S OWN SIDE (the 09-24
    # fix round, item 28c): the tariff trace read "export pace lag peaked at the 3rd percentile" for a
    # TROUGH; `render.extreme_verb` is the page's own producer of that verb, read and never re-typed.
    try:
        from leviathan.graphrag.state.render import chain_hop_name, extreme_verb
        name = chain_hop_name(rh) or _words(rh.driver_id)
    except Exception:                                   # noqa: BLE001 -- a name is never worth a turn
        name, extreme_verb = _words(rh.driver_id), (lambda _p: "peaked at")
    if rh.tail_peak > rh.tail and rh.tail_peak_percentile is not None and rh.tail_peak_date:
        from leviathan.graphrag.state.render import month_words
        pk = int(round(float(rh.tail_peak_percentile)))
        now = (("the %d%s" % (int(round(rh.percentile)), _pct_suffix(int(round(rh.percentile)))))
               if has_pct else latest)
        tail = (("; the declared lag runs to %s" % month_words(rh.tail_lag_to))
                if rh.tail_lag_to else "")
        return ("%s %s the %d%s percentile of its own record in %s and reads %s now%s"
                % (name, extreme_verb(pk), pk, _pct_suffix(pk), month_words(rh.tail_peak_date),
                   now, tail))
    return "%s sits at %s" % (name, latest)


def chain_explain(ch: Chain, *, named_markets=(), horizon_months: Optional[int] = None,
                  anchor: Optional[AnchorFacts] = None) -> Chain:
    """Fill a chain's seven PRINTABLE sentences -- one per rank term -- without moving its score.

    THE ARITHMETIC LINE IS WHAT MAKES THE SELECTION FALSIFIABLE ON THE PAGE (DESIGN B.2's closing
    sentence), so it is not optional; it is only DEFERRED, to the chains a reader or a payload
    actually meets. A pin asserts the score is byte-identical before and after.

    **THE SENTENCES ARE THE TRACE'S, AND THE PAGE'S ARE THE RENDER'S** (lane R's handoff W-1). They
    are register-clean here -- every driver id goes through ``render.humanise`` and every market slug
    through ``render.board_label``, pinned against ``register.internal_leaks`` and
    ``register.desk_register_hits`` on every rendered chain -- but the page's own chain rows are
    composed in ``render.py`` from ``Chain.terms`` and the hops' fields, so that the block can cite
    what it prints. A later lane that "fixes" the render by printing these notes would print a second
    spelling of one fact, not a missing one."""
    before = ch.score
    ch.notes = {}
    chain_score(ch, named_markets=named_markets, horizon_months=horizon_months,
                history=ch.history, with_notes=True, anchor=anchor)
    ch.score = before
    return ch


def _tail_order(hops) -> list:
    """The hop indexes by TAIL, loudest first. Ties break on the hop's own seat in ``Board.order`` and
    then on the driver id -- the board's OWN rank, never the alphabet, and never insertion order.

    THE MEASURE IS ``ChainHop.chain_tail`` -- the loudest reading inside the hop's own declared lag
    window (owner ruling 5) -- and it is the SAME measure the TAIL term scores, so the receipt hop and
    the term can never disagree about which reading is the loudest on a chain."""
    return sorted(range(len(hops)),
                  key=lambda i: (-hops[i].chain_tail, hops[i].seat, hops[i].driver_id))


def chain_receipt_index(hops) -> int:
    """WHICH hop is the chain's RECEIPT HOP -- the loudest by the TAIL measure (DESIGN B.2).

    ONE RULE, TWO READERS. The receipt hop decides where the dated action is looked for, which record
    the history stat reads, and which reading the diversity fold keys on, so the rule is a function
    rather than a line inside the scorer that a second caller would have to re-type."""
    order = _tail_order(hops)
    return order[0] if order else 0


def _pct_suffix(n: int) -> str:
    """``th`` / ``st`` / ``nd`` / ``rd`` -- the SUFFIX only. The number is a served figure and stays a
    digit; `render.ordinal_words` is the letters-only producer and is the render's to reach for."""
    if 10 <= (n % 100) <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _chain_lag_fit(ch: Chain, horizon_months: Optional[int]) -> tuple:
    """2 when the TOP hop's declared band contains the turn's horizon in quarters, 1 adjacent or when
    no horizon was asked, 0 disjoint. AN OPEN-ENDED BAND CONTAINS EVERY HORIZON AT OR PAST ITS START:
    ``structural`` opens and does not close (`event_is_open`'s own law), so a chain topped by a
    structural driver is not charged for a window the graph declined to close."""
    band = ch.hops[0].lag_band if ch.hops else None
    if horizon_months is None or band is None or band.min_q is None:
        return (1, "no horizon was asked, or the top of this chain declares no band")
    hq = max(1, int(round(float(horizon_months) / float(QUARTER_MONTHS))))
    lo = int(band.min_q)
    hi = None if band.max_q is None else int(band.max_q)
    if hi is None:
        return ((2, "the top of this chain declares an open window from quarter %d" % lo) if hq >= lo
                else (1, "the horizon asked about sits before this chain's declared window"))
    if lo <= hq <= hi:
        return (2, "the horizon asked about sits inside the top hop's own declared window")
    if abs(hq - lo) <= 1 or abs(hq - hi) <= 1:
        return (1, "the horizon asked about sits one quarter outside the top hop's declared window")
    return (0, "the horizon asked about sits outside the top hop's declared window")


def _receipt_in_reach(hp: ChainHop, asof: str) -> bool:
    """DESIGN B.4's OWN CLAUSE: a CLOSED receipt is the chain's only while it sits WITHIN ONE
    BAND-LENGTH of the as-of (review round 2 M7).

    ``NodeRow.event_date`` is ``max(event_date <= asof)`` over the node's receipts and is never aged
    out, so without this bound a 2019 action was a 2026 chain's printed receipt and scored the EVENT
    term 12 of 20. The WORDS were honest ("read as history: the window closed") -- this is not the E4
    lie -- but a rank term was inflated by a document nobody would call a receipt for today's chain,
    and the chain's own OPEN receipt (choice 1) is untouched because an open window is by definition
    still running.

    ONE BAND-LENGTH IS THE HOP'S OWN DECLARED MAXIMUM LAG, so the bound is the graph's rather than a
    number minted here; a hop that declares no band keeps the design's quarter. Where the chain carries
    no as-of (the offline ranking harness) there is nothing to age against and the receipt stands --
    the shipped behaviour, declared rather than silently inherited."""
    return _date_in_reach(hp.event_date, hp.lag_band, asof)


def _date_in_reach(event_date, band: Optional[LagBand], asof: str) -> bool:
    """:func:`_receipt_in_reach`'s rule on a bare DATE and BAND -- the ONE recency bound, read by the
    hop and by :func:`hop_event`'s classifier, which meets candidate documents before any hop exists."""
    if not asof or not event_date:
        return True
    lo_m, hi_m = (band.months() if band is not None else (None, None))
    hi = int(hi_m) if hi_m is not None else max(int(lo_m or 0), QUARTER_MONTHS)
    floor = _add_months(str(asof)[:10], -max(1, hi))
    if not floor:
        return True
    return str(event_date)[:10] >= floor


def _aged_receipt_keys(ch: Chain) -> set:
    """THE DATED ACTIONS THIS CHAIN'S OWN WINDOWS HAD SHUT ON, BY THE DOCUMENT'S OWN IDENTITY --
    ``(contract, driver_id, event_date)``, ONE ROW'S ONE ACTION COUNTED ONCE (round-4 census 3).

    **A DOCUMENT IS NOT A CHAIN-DOCUMENT PAIR.** :class:`ChainHop` is memoised per
    ``(contract, driver_id)``, so the SAME aged action rides every pool chain that walks that row --
    and a count line that summed the per-chain field over the pool printed "fifty-five / two hundred
    twenty / two hundred sixty-four dated actions aged out of their windows" on an estate holding
    EXACTLY ONE (measured at quick / deep / max). The product of chains and documents is not a
    document count, and the noun on the page says documents.

    THE KEY IS THE DOCUMENT'S OWN ADDRESS AND NOT THE PROPOSITION'S TEXT: ``NodeRow.event_date`` is
    ``max(event_date <= asof)`` per row, so one row carries at most one dated action here, and E11's
    rule -- the PAIR, never the bare driver id -- keeps one id's action on two markets two documents.
    :attr:`Chain.receipts_aged_out` stays the PER-CHAIN count (the chain's own answer to "how many
    documents did I have and not use"); this set is what :func:`chain_counts` folds over the POOL, and
    :data:`CHAIN_SEAM_FIELDS` says which name carries which."""
    if not ch.hops:
        return set()
    # THE HOP'S OWN EVENT WORD DECIDES (the 09-23 fix round): `action_aged` is exactly HEAD's condition
    # (a dated action, its window shut, older than one band-length) on every hop HEAD could read, and a
    # REGIME in force or a FORECAST is not an aged action -- the tariff turn's two "aged" documents were
    # policy actions still in force, which is what `regime_in_force` now says.
    return {(hp.contract, hp.driver_id, str(hp.event_date)[:10]) for hp in ch.hops
            if hp.event_receipt and hp.event_date
            and hop_event_kind(hp, ch.asof) == "action_aged"}


def _chain_receipt(ch: Chain) -> tuple:
    """DESIGN B.4's ORDER OF CHOICE at the chain's receipt hop, then along the rest of the chain.

    **AND THE RECEIPTS IT AGED OUT ARE COUNTED, NEVER SILENTLY DROPPED** (review MA-4). The recency
    bound below (:func:`_receipt_in_reach`) is the correction M7 asked for, and a correction that
    leaves no trace is a deletion: as-of 2026-09-07, a chain whose only dated action was 2024-01-01 on
    a 0-1 quarter hop read ``receipt_kind "none"`` with NO counter recording that the estate had the
    document at all -- indistinguishable, on the trace and in the count line, from a chain that never
    had one. The fourth element of the return is how many such documents this chain had; it scores
    NOTHING and it is COUNTED on :attr:`Chain.receipts_aged_out` and in :func:`chain_counts`.

    **AND THE AGED DOCUMENT IS RETURNED WITH THE HOP IT SITS ON AND ITS DATE** (round-4 census 4), the
    way every chosen branch returns the hop it read: the aged date is a ``max`` over whichever hops
    aged out, so a consumer that names the chain's RECEIPT hop beside it puts a dated fact under a
    relation the producer never declared it against. Elements five and six are that hop and that date,
    published on :attr:`Chain.aged_receipt_hop` / :attr:`Chain.aged_receipt_date`; and where nothing
    else was found the WORDS state the aged action (:data:`render.CHAIN_RECEIPT_AGED`, the estate's one
    spelling of it) instead of the empty string a reader met as "this turn retrieved nothing".

    **AND CHOICE (3) TAKES THE SAME RECENCY BOUND AS CHOICE (2)** (round-4 census 5). Without it the
    document choice (2) had just aged out came straight back under the MECHANISM label and scored 6 of
    20: measured on the census board, one page carried "ACTION SIX" in its arithmetic line beside a
    document row reading "aged out of the window declared for it", with ``receipt_kind = mechanism``
    on the same chain -- two producers disagreeing about ONE document on ONE page. The bound is the
    SHIPPED predicate and it is not re-typed: the candidate's own date is carried on a REAL hop
    (``dataclasses.replace``, ``render.chain_receipt``'s own idiom) and :func:`_receipt_in_reach`
    decides. A report sentence older than the hop's own declared window is NOT a deletion where it is
    refused -- the term reads the tier the window supports and ``notes['event']`` says exactly that
    ("no dated document in this hop's window among the documents this turn retrieved").

    **THE EVENT RECEIPT NEEDS NO SEAM ARGUMENT.** ``walk._stage2`` sets ``row.receipts`` /
    ``row.event_date`` / ``row.event_receipt`` / ``row.event_open`` for EVERY row of ``bd.rows``
    (:1687-1693), not only the loud set, and ``_receipt_summary`` carries up to three FULL proposition
    dicts per row. The S8 recon measured the render printing both classes today with
    ``receipts_by_row`` absent, so what the chain's receipt of first choice needs is already in hand;
    only choice (3)'s wider mechanism draw wants the seam argument, and ``row.receipts['top']`` gets
    most of the way there for free.

    A RECEIPT OUTSIDE ITS WINDOW RENDERS WITH THE WORDS AND NEVER INSIDE IT (E4): the correction, not
    the deletion. A receipt dated after the as-of never reaches here at all -- ``event_receipt_for``
    is the ONE rule and it already refuses one (:1011)."""
    order = [ch.receipt_index] + [i for i in range(len(ch.hops)) if i != ch.receipt_index]
    keys = _aged_receipt_keys(ch)
    # THE NEWEST AGED DOCUMENT, AND THE HOP IT ACTUALLY SITS ON (census 4). The date is a `max` over
    # the aged set and the hop is the one carrying THAT date -- read in `order`, so the receipt hop
    # wins a tie and the answer is the board's own seat rather than insertion order.
    aged_date = max((k[2] for k in keys), default="")
    aged_hop = next((ch.hops[i] for i in order
                     if str(ch.hops[i].event_date or "")[:10] == aged_date
                     and (ch.hops[i].contract, ch.hops[i].driver_id, aged_date) in keys),
                    None) if keys else None
    aged = (len(keys), aged_hop, aged_date)
    refused_date, refused_hop = "", None
    # THE HOPS' OWN EVENT WORDS (CONTRACT C7), read once. Every choice below is DESIGN B.4's, over those
    # words: (1) an open action, (2) a closed action in reach OR a regime in force -- the same points,
    # owner decision 3 -- (3a) a dated forecast, (3b) a report sentence in reach; and `ch.event_kind`
    # is stamped by the SAME branch that returns, so the word and the points name one document.
    kinds = [hop_event_kind(h, ch.asof) for h in ch.hops]
    for i in order:
        hp = ch.hops[i]
        if kinds[i] == "action_open" and hp.event_receipt and hp.event_date:
            ch.event_kind = "action_open"
            return ("open", dict(hp.event_receipt),
                    "a dated action %s, and the window this chain declares for it is still open"
                    % _action_when(hp), *aged)
    for i in order:
        hp = ch.hops[i]
        if kinds[i] in ("action_closed", "regime_in_force") and hp.event_receipt and hp.event_date:
            ch.event_kind = kinds[i]
            if kinds[i] == "regime_in_force":
                return (EVENT_KIND_RECEIPT["regime_in_force"], dict(hp.event_receipt),
                        CHAIN_REGIME_WORDS % _action_when(hp), *aged)
            return ("closed", dict(hp.event_receipt),
                    "a dated action %s, read as history: the window closed" % _action_when(hp),
                    *aged)
    for i in order:
        hp = ch.hops[i]
        # (3a) A DATED REPORT WRITTEN INSIDE THE PERIOD IT IS ABOUT (review WT F-1): the mechanism tier,
        # ahead of a forecast; its words never say "forecast" nor "not an action".
        if kinds[i] == "report_in_reach" and hp.event_receipt and hp.event_date:
            ch.event_kind = "report_in_reach"
            _doc = str((hp.event_receipt or {}).get("date") or "")[:10] or "an undated day"
            # AN UNPLACED EVENT DATE (no precision, K6 rule 1) IS NEVER PRINTED: the document's own date is
            # the one date this receipt reliably carries, so the words carry that date alone.
            return (EVENT_KIND_RECEIPT["report_in_reach"], dict(hp.event_receipt),
                    (CHAIN_DATED_REPORT_WORDS % (_doc, _action_when(hp)) if hp.event_interval
                     else CHAIN_DOCUMENT_DATED_WORDS % _doc), *aged)
    for i in order:
        hp = ch.hops[i]
        if kinds[i] == "guidance" and hp.event_receipt and hp.event_date:
            ch.event_kind = "guidance"
            return (EVENT_KIND_RECEIPT["guidance"], dict(hp.event_receipt),
                    CHAIN_GUIDANCE_WORDS % (
                        str((hp.event_receipt or {}).get("date") or "")[:10] or "an undated day",
                        _action_when(hp)), *aged)
    for i in order:
        hp = ch.hops[i]
        for r in hp.receipts_top:
            if not (isinstance(r, dict) and r.get("date")):
                continue
            rd = str(r["date"])[:10]
            # ONE RECENCY RULE, READ BY BOTH CHOICES (census 5): a document this chain's own declared
            # window has shut on is not its receipt under a SECOND label either. WHAT IT REFUSED IS
            # RECORDED (round-5 blocker 1): the newest refused date and the hop it sits on, so the
            # page can NAME the report sentence it will not cite and the count line can count it.
            if not _receipt_in_reach(replace(hp, event_date=rd), ch.asof):
                if rd > refused_date:
                    refused_date, refused_hop = rd, hp
                continue
            ch.event_kind = "report_in_reach"
            return ("mechanism", dict(r),
                    "a dated report sentence about this hop's mechanism, %s" % rd, *aged)
    # NOTHING CHOSEN: what the mechanism bound refused rides the chain (blocker 1) before either return.
    ch.mechanism_refused_hop, ch.mechanism_refused_date = refused_hop, refused_date
    if aged_date:
        # THE AGED ACTION IS STATED WHERE THE CHAIN WOULD OTHERWISE HAVE SAID IT RETRIEVED NOTHING,
        # in the render's own spelling of the sentence so the two producers cannot drift.
        from leviathan.graphrag.state.render import CHAIN_RECEIPT_AGED
        ch.event_kind = "action_aged"
        return ("none", None, CHAIN_RECEIPT_AGED % aged_date, *aged)
    if refused_date:
        # A REPORT SENTENCE OUTSIDE THE WINDOW IS NAMED, in the render's own spelling, never dropped.
        from leviathan.graphrag.state.render import CHAIN_RECEIPT_REPORT_OUTSIDE
        ch.event_kind = "report_outside"
        return ("none", None, CHAIN_RECEIPT_REPORT_OUTSIDE % refused_date, *aged)
    ch.event_kind = "none"
    return ("none", None, "", *aged)


#: THE TRACE'S WORDS FOR A REGIME IN FORCE (owner decision 3). They name the ACTION and the RULE and
#: never assert that any policy is in force today -- the newest dated action the turn RETRIEVED is the
#: fact, and "read as in force until a later dated action" is the model's declared rule, stated as one.
#: The page's own words are the render's (CONTRACT C7).
CHAIN_REGIME_WORDS: str = ("the newest dated policy action on this link that this turn retrieved is "
                           "dated %s, and a policy is read as in force until a later dated action on "
                           "the same link")
#: THE TRACE'S WORDS FOR A DATED FORECAST -- its publication date, the interval it is about AT ITS
#: PRECISION, and what it is not.
CHAIN_GUIDANCE_WORDS: str = ("a dated forecast published %s about events %s, read as guidance and not "
                             "as an action")
#: THE TRACE'S WORDS FOR A DATED REPORT WRITTEN INSIDE THE PERIOD IT DESCRIBES (review WT F-1): its
#: publication date and the period AT ITS PRECISION -- a report, never called a forecast, never "not an
#: action" (whether it states a realised or a conditional event is an extraction fact, docketed).
CHAIN_DATED_REPORT_WORDS: str = "a dated report published %s about events %s"
#: THE TRACE'S WORDS FOR A DATED REPORT WHOSE EVENT DATE CARRIES NO DECLARED PRECISION (CONTRACT K6, rule
#: 1 of :func:`hop_event`): the document's own date and nothing else -- the stored event date is a
#: first-of-period normalisation nobody wrote, and it is never printed as a day.
CHAIN_DOCUMENT_DATED_WORDS: str = "a dated report published %s"



def _action_when(hp: ChainHop) -> str:
    """A hop's event date AT ITS PRECISION for the trace's receipt sentence: ``on <ISO>`` for a day
    (or an undeclared precision) -- HEAD's own spelling, byte for byte -- and ``during 2026`` /
    ``in the first quarter of 2026`` / ``in January 2026`` for a coarser one, which is what the date
    actually says (cotton FA-5)."""
    prec = str(getattr(hp, "event_precision", "") or "").strip().lower()
    if prec in ("year", "quarter", "month"):
        iv = tuple(getattr(hp, "event_interval", ()) or ()) or event_interval(hp.event_date, prec)
        words = event_when_words(iv, prec)
        if words:
            return words
    return "on %s" % hp.event_date


# ── the render decision: the print line, the diversity rule and the SIGN diversity rule ─────────────
def _slot_subject(c: Chain, subject_ids: Optional[dict], question_markets=None) -> bool:
    """Does this chain carry the driver THE TURN IS ANCHORED ON? (the SUBJECT slot's own test)

    ``subject_ids`` is ``{contract: frozenset(driver ids)}`` and the test is keyed on the PAIR, never
    on the bare id (E11): ``area`` is a driver of corn AND of wheat and the two read the 98th and the
    1st percentile on the same turn, so a flat id set would seat a wheat chain for a corn subject.
    The ids are the planner's own -- ``Board.subject_ids_on`` plus the ``attached_event`` anchor's
    driver -- so NO new detection is minted here: the planner's own slot is consumed one seat further.
    A node folded into a link (:attr:`ChainHop.aliases`, K12) is still a node the chain walks.

    **AND THE CHAIN RUNS ON, OR INTO, ONE OF THE QUESTION'S OWN MARKETS** (CONTRACT K9).
    ``question_markets`` is the distance-0 set of :func:`question_reach`; where it is given a subject
    chain must sit on one of those markets or terminate on one. MEASURED on 09-24: the deep and max
    soybean turns seated a safrinha CORN chain (``campinas_corn_reference_bmf`` into DCE soybeans)
    under the label "the chain this question names". ``None`` -- no reach computed -- is HEAD's test."""
    ids = (subject_ids or {}).get(str(c.contract or "")) or ()
    if not (bool(ids) and any(h.driver_id in ids or any(a in ids for a in (h.aliases or ()))
                              for h in c.hops)):
        return False
    if question_markets is None:
        return True
    return str(c.contract or "") in question_markets or str(c.terminal or "") in question_markets


def _slot_pair(c: Chain, named_contracts) -> bool:
    """Does this chain make the PAIR CALL a multi-market question demands? -- its terminal reaches a
    market the QUESTION named, and it is not the chain's own anchor. Silent where fewer than two
    markets were named, because a pair call is not a thing one market can make."""
    named = {str(x) for x in (named_contracts or ()) if str(x or "")}
    if len(named) < 2:
        return False
    t = str(c.terminal or "")
    return bool(t) and t in named and t != str(c.contract or "")


def _slot_horizon(c: Chain, horizon_months: Optional[int]) -> bool:
    """Does this chain's DECLARED LAG BAND contain the horizon the question asked about? ONE reader of
    one rule: :func:`_chain_lag_fit`'s own ``2`` branch, which is exactly "the horizon sits inside the
    top hop's declared window" (an open-ended band contains every horizon at or past its start)."""
    if horizon_months is None:
        return False
    return int(_chain_lag_fit(c, horizon_months)[0]) >= 2


def chain_render_set(chains, *, k: int, print_line: float = 40.0, subject_ids: Optional[dict] = None,
                     named_contracts=(), horizon_months: Optional[int] = None,
                     subject_off: str = "not_asked", question_markets=None) -> dict:
    """WHICH chains render, and WHY -- a RENDER rule the object exposes, never a filter on the pool.

    THE RULES, IN ORDER:
      1. the pool is in :attr:`Chain.rank` order (score, then depth, then the receipt hop's own seat);
      2. **DIVERSITY**: no two rendered chains share their TOP reading or their RECEIPT reading, folded
         on the SERIES KEY (:attr:`ChainHop.fold_key`) so ONE series is counted ONCE in ONE spelling.
         Without the second clause the offline demo returned three routes to one reading
         (``psd_ending_stock_su_ratio`` at the 1st percentile, three times);
      3. **THE PRINT LINE IS RETIRED AS A SELECTION RULE** (owner ruling 6, 2026-09-18). The top K of
         THIS BOARD render, always: the rank is RELATIVE WITHIN ONE TURN, so a data-poor anchor still
         gets its best chains and a low score reads as SCARCE DATA (``Chain.scope`` states which terms
         had anything to read) rather than as a bad chain. The line survives as ONE decision and one
         only -- FULL block versus ONE line with its own arithmetic -- and it can never render fewer
         than K;
      4. **SIGN DIVERSITY** (owner, 2026-09-17): disagreement is where convexity lives and it must be
         STRUCTURAL rather than left to the writer to notice. Where both sides of the anchor carry a
         chain above the print line, the render carries the best FOR and the best AGAINST; where only
         one side exists, the block SAYS so.
      5. **THE RENDER SLOTS** (owner ruling 2026-09-22), the same shape as sign diversity: after the
         top K and the sign swap, LABELLED seats that THE QUESTION anchors -- ``subject`` (a chain
         carrying the driver this turn is anchored on), ``pair`` (a chain whose terminal reaches a
         SECOND market the question named), ``horizon`` (a chain whose declared band contains the
         horizon asked about). Each takes the BEST-RANKED chain in the pool that satisfies it and is
         not already picked. **A SLOT ADDS NO ROW WHERE THE TOP K ALREADY CARRIES A QUALIFYING
         CHAIN**, and **A SLOT NEVER MOVES THE RANK**: the graph decides relevance and the question
         only anchors, so a slot reserves a seat and changes no order. The routing fields (``steps``,
         ``mode``, ``fallback``, ``subject_hints_n``, ``degraded``) select NOTHING here and this
         function reads none of them.

    **FULL VERSUS ONE LINE IS THE CAP'S DECISION AND NO LONGER THE SCORE'S** (owner ruling 6(a),
    closed at review MA-1). The first cut stamped ``c.full = c.score >= print_line`` on EVERY chain in
    the pool, so ONE FIELD carried two readings -- "render this one in full" and "this one is below the
    page's selection line" -- and the count line read the wrong one. MEASURED on the data-poor pool
    ruling 6(a) was written for (four chains at 30 / 22 / 15 / 9, k=3): three chains rendered, ALL
    THREE as one-liners, while ``below_print_line`` said four of four sat below a line three of them
    were printed above. The top K render IN FULL, always; the only thing that renders as one line now
    is a SLOT chain past the ``K + 2`` full bound (:data:`CHAIN_SLOT_FULL_OVER_K`), which is never
    dropped and is counted (``chain_counts["rendered_one_line"]``); and how many chains sit below the
    print line is computed from the SCORE, in :func:`chain_counts`, where it is true.

    **AND THE BOUND IS STAMPED IN SEAT ORDER, NEVER ON THE POST-SORT POSITION** (round-3 review
    MA-R3-1, orchestrator ruling 2026-09-22). The seats are taken in ONE declared order -- the top K,
    then the sign swap, then the three slots -- and the sort that follows is for DISPLAY. Counting the
    bound off the SORTED list reduced whichever chain the RANK put last, and on a pool where the slot
    candidates outrank a top-K pick that is a TOP-K chain: measured at k=3 with the top K at
    99 / 70 / 40 and three fold-duplicate slot chains at 98 / 97 / 96, the 40.0 TOP-K chain took the
    one-line form while ``below_print_line`` said nothing sat below the line. ``k <= 0`` renders
    NOTHING, the slots included (review round 3, MINOR 2).

    **AND EACH QUESTION SLOT'S OUTCOME IS STAMPED BY THE BRANCH THAT DECIDED IT** (CONTRACT C7, the
    09-23 re-smoke's D9: ``slot_subject 0`` on ten of ten turns read as "never lit" while the resolver
    had never run). ``counts["slot_state"]`` carries one :data:`SLOT_STATES` word per slot, written
    inside the same ``continue`` / seat branches below -- never a second computation. ``subject_off`` is
    the SUBJECT slot's word when no subject id reached the pool (``resolver_off`` where the resolver
    payload never ran, the caller's reading of ``Board.subject``); PAIR and HORIZON are ``not_asked``
    when the question anchors neither. The five ``slot_*`` seat counts are unchanged, byte for byte.
    Every pool chain also carries the live slots it ANSWERS (:attr:`Chain.slot_fits`), from the same
    tests, so the bounded trace payload can carry each live slot's best candidate.

    **A PREMISE NOT IN FORCE TAKES NO SEAT** (CONTRACT K13): a chain whose first hop is the phase the
    reading does not put in force (:attr:`Chain.premise_off`) is refused by the top K, by the sign swap
    and by every question slot; it stays in the pool with its score and its trace row and is counted.
    ``question_markets`` (K9) is the question's own markets, which the SUBJECT slot's test reads.

    **AND THE HORIZON'S CHAIN IS NAMED** (CONTRACT K21): where the horizon slot is ``seated`` or
    ``answered_by_rank``, exactly one rendered chain -- the seated one, else the best-ranked rendered
    chain the slot's own test passes -- carries :attr:`Chain.answers_horizon`, and the head's horizon
    row prints that chain's outcome.

    Returns ``{"rendered": [...], "counts": {...}, "disagreement": <one sentence>}`` and stamps
    :attr:`Chain.rendered` / :attr:`Chain.full` / :attr:`Chain.slot` / :attr:`Chain.decline` on every
    chain in the pool."""
    pool = sorted(chains or (), key=lambda c: c.rank)
    for c in pool:
        c.rendered, c.full = False, False
        c.slot = ""
        c.decline = None
        c.slot_fits = ()
        c.answers_horizon = False
    # THE QUESTION SLOTS' OUTCOMES, one closed word each. A slot the question does not anchor keeps its
    # not-live word; a live slot's word is overwritten by the branch below that decides it.
    slot_state = {"subject": (subject_off if subject_off in SLOT_STATES else "not_asked"),
                  "pair": "not_asked", "horizon": "not_asked"}
    k = max(0, int(k))
    picked: list = []
    tops: set = set()
    receipts: set = set()

    def _horizon_tape_ok(c) -> bool:
        # THE HORIZON ROW READS THE CHAIN'S OWN CONTRACT'S TAPE (`_outcome_for`: `bd.tape[ch.contract]`), so
        # the chain that answers a horizon must sit ON one of the question's own markets AND land on one -- a
        # driver board's chain into the question market would print THAT board's price history as the answer,
        # and a question-market chain that lands on another board ("China import tariff into BMF corn") would
        # print the question market's price under a relation that ends elsewhere (REVIEW_WT MAJOR-3 / RA M5).
        # `None` (no reach) is HEAD's reading.
        return question_markets is None or (str(c.contract or "") in question_markets
                                            and str(c.terminal or c.contract or "") in question_markets)

    def _fits(c, ts: set, rs: set) -> bool:
        # ONE READING, EVERY NAME OF IT (W-3): the identity SETS meet or they do not.
        tk, rk = c.fold_idents()
        return not (tk & ts) and not (rk & rs)

    def _seat(c, slot: str) -> None:
        tk, rk = c.fold_idents()
        tops.update(tk)
        receipts.update(rk)
        c.slot = slot
        picked.append(c)

    def _on_question(c) -> bool:
        # FIXER PASS (REVIEW_WT MAJOR-3 / RA M5): K9 bounds the ANCHORS to the question's reach, and the SEATS
        # must be bounded the same way -- a chain whose contract and terminal both lie outside the
        # question's own markets (distance 0) runs between boards the question never named ("CBOT corn
        # China state reserves into sorghum" on a soybean page) and is COUNTED, never seated. `None` (no
        # reach computed: the resolver never reached the turn) is HEAD's reading.
        if question_markets is None:
            return True
        return str(c.contract or "") in question_markets or str(c.terminal or "") in question_markets

    def _take(c, slot: str = "top") -> bool:
        if getattr(c, "premise_off", False) or not _on_question(c) or not _fits(c, tops, receipts):
            return False
        _seat(c, slot)
        return True

    # **A CAP OF ZERO RENDERS NOTHING, AND A SLOT DOES NOT OUTVOTE IT** (review round 3, MINOR 2).
    # `chain_rows` reads `int(getattr(knobs, "chain_render_k", 0) or 0)`, so a knobs object WITHOUT
    # the column arrives here at zero -- and before this guard clause (5) still seated three chains:
    # MEASURED on the five-chain pool with all three slots live, k=0 rendered THREE (subject, pair,
    # horizon), TWO of them in full, because the bound is `0 + 2`. A slot is a seat BESIDE the top K
    # and never instead of it, so where the page asked for no chains there is no seat to take.
    if k > 0:
        for c in pool:
            if len(picked) >= k:
                break
            _take(c)
        # (4) SIGN DIVERSITY -- both sides of the anchor when both sides carry a chain.
        if k >= 2 and picked:
            sides = {c.side for c in picked}
            missing = ({"for", "against"} - sides) if ("for" in sides
                                                       or "against" in sides) else set()
            if len(missing) == 1:
                want = missing.pop()
                _swap_in_other_side(pool, picked, tops, receipts, want=want, k=k,
                                    take=lambda c: _take(c, "sign"), fits=_fits)
        # (5) THE RENDER SLOTS -- a seat the QUESTION anchors, taken only where the rank left it
        # empty. EACH SLOT IS SKIPPED BEFORE THE POOL IS TOUCHED WHERE THE QUESTION ANCHORS NOTHING,
        # so a turn with no subject, one named market and no horizon does not walk two thousand
        # candidates three times to conclude what its own inputs already said -- and the pre-slot
        # render set is then the set by construction rather than by coincidence.
        for word, live, test in (("subject", bool(subject_ids),
                                  lambda c: _slot_subject(c, subject_ids, question_markets)),
                                 ("pair", len({str(x) for x in (named_contracts or ())}) >= 2,
                                  lambda c: _slot_pair(c, named_contracts)),
                                 ("horizon", horizon_months is not None,
                                  lambda c: _slot_horizon(c, horizon_months) and _horizon_tape_ok(c))):
            if not live:
                continue
            fits = [c for c in pool if test(c) and not getattr(c, "premise_off", False) and _on_question(c)]
            for c in fits:
                c.slot_fits = tuple(c.slot_fits) + (word,)
            if any(test(c) for c in picked):
                slot_state[word] = "answered_by_rank"
                continue                                 # the top K already answers this slot
            taken = {id(c) for c in picked}
            cands = [c for c in fits if id(c) not in taken]
            if not cands:
                slot_state[word] = "no_candidate"
                continue
            # THE SEAT TAKES THE BEST-RANKED CHAIN THAT ANSWERS THE QUESTION (the 09-25 fix round, item
            # W-1 / N2): the graph decides relevance and the question only anchors, so the rank decides
            # which qualifying chain sits here -- and THE DIVERSITY FOLD ORDERS ONLY WITHIN A RANK TIE
            # (:func:`_slot_pick`). MEASURED on the 09-25 deep and max soybean turns: the fold preference
            # skipped the best horizon chain (crude -> crush -> stocks-to-use -> calendar spread -> CBOT
            # soybeans, 68.5 deep / 62.5 max) because its TOP reading (Brent) was already on the page,
            # and seated the Thai TRQ chain (59.1, its weakest declared link LOW, its only document a
            # 2019 note) -- and both TL;DRs then said "the chain from Thai imports answers the horizon".
            # A slot never moves the rank; it reserves a seat for the chain the rank already prefers.
            # The rejected lexical forms: excluding TRQ ids, or a confidence floor keyed on driver names.
            _seat(_slot_pick(cands, lambda c: _fits(c, tops, receipts)), word)
            slot_state[word] = "seated"
    # **THE FULL BOUND IS STAMPED IN SEAT ORDER AND THE SORT IS FOR DISPLAY** (round-3 review MA-R3-1,
    # orchestrator ruling 2026-09-22). `picked` is in the order the seats were TAKEN -- the top K and
    # the sign swap by construction, then the three slots -- and the bound belongs to that order: the
    # top K render in full ALWAYS (ruling 6(a)) and the only thing that can be reduced is a SLOT chain
    # past `K + 2`. Stamping `i < K + 2` on the POST-SORT position handed the reduction to whichever
    # chain the RANK put last, and the chains that can outrank a top-K pick are exactly the slot
    # candidates, because clause (5) bypasses the diversity fold as a veto. MEASURED on the reviewer's
    # own pool (k=3, top K at 99 / 70 / 40 and three fold-duplicate slot chains at 98 / 97 / 96, all
    # three slots live): the 40.0 TOP-K chain was reduced to the one-line form and the page printed
    # "under this page's own selection line" over it while `below_print_line` said ZERO chains sat
    # below the line -- one field carrying two readings again, one round after MA-1 closed it.
    # (Round 5: the seat past the K+2 bound now prints "carried in one line, past the page's
    # full-render bound"; the sentence quoted above is what the page printed BEFORE that.)
    seat_order = list(picked)
    picked.sort(key=lambda c: c.rank)
    for c in picked:
        c.rendered = True
    # THE HORIZON'S CHAIN (K21): the seated one, else the best-ranked rendered chain the slot's test passes.
    if slot_state.get("horizon") in ("seated", "answered_by_rank"):
        _hz = (next((c for c in picked if c.slot == "horizon"), None)
               or next((c for c in picked if _slot_horizon(c, horizon_months) and _horizon_tape_ok(c)),
                       None))
        if _hz is not None:
            _hz.answers_horizon = True
    _full_cap = k + int(CHAIN_SLOT_FULL_OVER_K)
    for i, c in enumerate(seat_order):
        c.full = i < _full_cap
    for c in pool:
        if c.rendered:
            continue
        # THE WORD NAMES THE CAUSE. With the print line retired as a selection rule (ruling 6) every
        # unrendered chain is one the page's own cap or its diversity fold beat -- `render_cap` -- and
        # the one distinct fact left is a chain that could carry no reading at all. Naming a chain
        # `below_print_line` for a cut the line no longer makes would be a reason that is not the
        # cause; the COUNT of chains below the line is kept, on `chain_counts`, where it is true.
        c.decline = "render_cap" if c.measured_hops else "no_measured_hop"
    counts = chain_counts(pool, print_line=float(print_line), slot_state=slot_state)
    if question_markets is not None:
        # the chains the seat test refused (REVIEW_WT MAJOR-3), COUNTED at the tail of the counts
        counts["off_question"] = sum(1 for c in pool if not _on_question(c))
    return {"rendered": picked, "counts": counts,
            "disagreement": chain_disagreement_words(picked)}


def _slot_pick(cands, fits):
    """THE ONE SEAT RULE FOR A QUESTION SLOT (the 09-25 fix round, W-1 / N2): the best-ranked candidate,
    with the diversity fold ordering ONLY among the candidates that TIE it on the rank's measured term
    (the score, at the precision :attr:`Chain.rank` reads it). ``cands`` is in rank order; ``fits`` is the
    fold test. A candidate below the best on score never takes the seat for folding cleanly -- novelty
    is not relevance."""
    best = cands[0]
    tie = round(float(best.score), 4)
    return next((c for c in cands if round(float(c.score), 4) == tie and fits(c)), best)


def _swap_in_other_side(pool, picked, tops: set, receipts: set, *, want: str, k: int, take, fits):
    """THE SIGN-DIVERSITY CLAUSE'S OWN SWAP -- and it TESTS THE REPLACEMENT BEFORE IT DROPS ANYTHING
    (review round 2 M4).

    **THE FIRST CUT COULD RENDER K-1.** It removed the worst chain on the crowded side and only THEN
    called ``_take(other)``, which can refuse ``other`` on the diversity fold -- so the page rendered
    ONE chain where three cleared the line. MEASURED: k=2 with a 90 FOR, an 80 FOR and a 70 AGAINST
    that shares the 90's receipt reading rendered exactly one chain, and the doctrine's anti-padding
    clause says fewer than K is right only when fewer EXIST, never when more did.

    The swap now composes: for each candidate on the missing side, in rank order, it looks for a drop
    on the crowded side (worst first) that would ADMIT it, and executes only a swap that closes. Where
    no pair closes, the picked set is left exactly as the rank chose it -- K chains, one side, and the
    disagreement line says the other side is absent, which is the honest reading of that board."""
    others = [c for c in pool if c.side == want and c not in picked]
    if not others:
        return
    for other in others:
        if len(picked) < k:
            if take(other):
                return
            continue
        # THE BOARD'S TOP CHAIN IS NEVER THE ONE DROPPED. It is the highest-ranked chain on the turn
        # and the one rule the whole selection agrees on; a diversity clause that unseats it would let
        # the second-best chain decide what the page leads with.
        over = [c for c in picked[1:] if c.side != want]
        for drop in reversed(over):
            keep = [c for c in picked if c is not drop]
            ts = set()
            rs = set()
            for c in keep:
                tk, rk = c.fold_idents()
                ts.update(tk)
                rs.update(rk)
            if not fits(other, ts, rs):
                continue
            # THE DROPPED CHAIN GIVES UP ITS SEAT WORD (the 09-25 fix round, W-4 / N12): it no longer
            # renders, so its trace row must not keep reading `slot "top"` beside `rendered false` --
            # MEASURED on 2024 chain 4, deep 2026 chain 7 and cocoa chain 5.
            drop.slot = ""
            picked[:] = keep
            tops.clear()
            tops.update(ts)
            receipts.clear()
            receipts.update(rs)
            take(other)
            return


def chain_disagreement_words(rendered) -> str:
    """The one line that says WHERE THE CHAINS DISAGREE, or that they do not.

    It names the hop that runs against the direction DECLARED for it, because that hop is the whole
    content of the disagreement and a reader asked to notice it unaided will not.

    IT IS THE TRACE'S SENTENCE AND ``render.sb_chain_sides`` IS THE PAGE'S -- two surfaces, declared
    (lane R's handoff W-2). Both are register-clean: the hops are named through the estate's ONE
    display vocabulary and the charged token ``the graph`` is spent by neither."""
    if not rendered:
        return ""
    from leviathan.graphrag.state.render import words_for_int
    sides = {c.side for c in rendered}
    against = []
    for c in rendered:
        against.extend(c.against_hops)
    seen: list = []
    for a in against:
        if a not in seen:
            seen.append(a)
    one = len(rendered) == 1
    if "for" in sides and "against" in sides:
        head = "these chains point opposite ways for this market"
    elif sides == {"unsettled"}:
        head = ("the one chain carried here settles no direction for this market today" if one else
                "not one of these chains settles a direction for this market today")
    elif len(sides) == 1:
        # ONE SIDE IS A FACT AND THE BLOCK SAYS IT (owner, 2026-09-17: "when only one side exists, say
        # so"). A page that prints three bullish chains and stays silent about the absence of a
        # bearish one has told the reader something it did not measure.
        only = "higher" if "for" in sides else "lower"
        head = ("the one chain carried here points %s for this market, and no other chain carried "
                "here points the other way" % only if one else
                "every chain carried here points %s for this market, and none points the other way"
                % only)
    else:
        head = "one of these chains settles a direction for this market and the others do not"
    if not seen:
        return head + "; no hop on it runs against the direction declared for it" if one             else head + "; no hop on them runs against the direction declared for it"
    return "%s; %s %s runs against the direction declared for it (%s)" % (
        head, words_for_int(len(seen)), "hop" if len(seen) == 1 else "hops",
        ", ".join(_words(a) for a in seen))


def chain_counts(pool, *, print_line: float = 40.0, slot_state: Optional[dict] = None) -> dict:
    """The honest COUNT LINE's own arithmetic (DESIGN B.3) -- every chain the graph carried, by fact.

    It replaces the SB-X ``path_render_cap`` enumeration, so it counts and never names: the names are
    the thing A.8 cuts. ``cross_unpriced`` is stamped by the builder, not here.

    ``print_line`` IS READ HERE AND NOWHERE ELSE IN THE SELECTION (review MA-1). It decides no chain's
    fate -- :func:`chain_render_set` takes the top K whatever they scored -- and the one thing it
    answers is the count line's own "how many sat below this page's selection line". The default is
    :func:`chain_render_set`'s own, for the caller that has no knob."""
    pool = list(pool or ())
    rendered = [c for c in pool if c.rendered]
    # THE DISTINCT COUNTS ARE BESIDE THE RAW ONES AND NEITHER REPLACES THE OTHER. The pool is
    # `paths x earned crosses`, so "reaching a market this question did not name" over the raw pool
    # counts one path five times when five far markets were priced -- a true number that reads as
    # noise. The MARKETS and the hop SEQUENCES are what a reader is actually being told about.
    return {"total": len(pool), "rendered": len(rendered),
            # HOW MANY RENDERED CHAINS TOOK THE REDUCED FORM -- never dropped, counted. A rendered
            # chain is one-line ONLY where a SLOT seated it past the K + 2 full bound.
            "rendered_one_line": sum(1 for c in rendered if not c.full),
            # THE REPORT SENTENCES THE MECHANISM BOUND REFUSED (round-5 blocker 4): its own key, its
            # own noun; never folded into receipts_aged_out (actions). **AND IT COUNTS DOCUMENTS, NOT
            # CHAINS** (the 09-23 re-smoke: cocoa printed 42 of 57 -- one refused report rides every
            # pool chain that walks its memoised hop, and the pool carried THREE). Folded on the
            # document's own identity exactly as `receipts_aged_out` is (round-4 census 3); the
            # per-chain field (`Chain.mechanism_refused_*`) is unchanged.
            "mechanism_refused": len({k for k in (_refused_report_key(c) for c in pool) if k}),
            "distinct_sequences": len({(c.contract, c.hop_ids) for c in pool}),
            "distinct_markets": len({c.terminal for c in pool if c.terminal}),
            "distinct_unnamed_markets": len({c.terminal for c in pool if c.unnamed_terminal}),
            # THE LINE IS A COUNT AND NO LONGER A CUT (owner ruling 6): how many chains sit below this
            # page's own selection line is a fact worth printing; that none of them was REMOVED for it
            # is the ruling. IT IS COMPUTED FROM THE SCORE AND IT COUNTS THE CHAINS THAT DID NOT
            # RENDER (review MA-1): `Chain.full` now means "rendered in full", so reading it here said
            # four of four sat below a line three of them were printed above.
            "below_print_line": sum(1 for c in pool
                                    if not c.rendered and float(c.score) < float(print_line)),
            "render_cap": sum(1 for c in pool if c.decline == "render_cap"),
            "no_measured_hop": sum(1 for c in pool if c.decline == "no_measured_hop"),
            # ORTHOGONAL SHOCKS (orchestrator note 3): a chain that crosses a commodity boundary on an
            # EARNED cross edge while carrying a dated event is an event entering from a market the
            # question did not name. The count line names how many existed and how many rendered, so a
            # turn with none reads as "no cross-market event reached this page" and never as silence.
            "cross_market_event": sum(1 for c in pool if c.cross and c.unnamed_terminal
                                      and c.receipt_kind in ("open", "closed")),
            "cross_market_event_rendered": sum(1 for c in rendered if c.cross and c.unnamed_terminal
                                               and c.receipt_kind in ("open", "closed")),
            # THE DOCUMENTS THE WINDOW HAD CLOSED ON (review MA-4). The estate retrieved a dated
            # action, the chain's own declared band had shut on it more than one band-length before
            # the as-of, so it scores NOTHING -- and it is counted here rather than made
            # indistinguishable from a chain that never had one. A fence CORRECTS or COMPUTES.
            #
            # **IT IS ONE POPULATION -- DOCUMENTS -- EVERYWHERE THE NAME APPEARS** (round-3 review
            # MA-R3-2, orchestrator ruling 2026-09-22). `Chain.receipts_aged_out` counts the aged-out
            # actions ON ONE CHAIN and this key counted the CHAINS that had at least one, so the same
            # word carried two numbers into `Board.trace()`, the census record and the arm's report:
            # MEASURED through the shipped producer on a board with TWO aged hops, the chain said 2
            # and the count line said 1. It is the law MA-5 closed for the firings noun -- one series,
            # counted ONCE, in ONE spelling -- and the count line is the surface that would print it.
            #
            # **AND SUMMING THE FIELD OVER THE POOL WAS NOT A DOCUMENT COUNT EITHER** (round-4 census
            # 3): `ChainHop` is memoised per `(contract, driver_id)`, so one aged action rides every
            # pool chain that walks that row and the sum printed 55 / 220 / 264 "dated actions aged
            # out of their windows" at quick / deep / max ON AN ESTATE HOLDING EXACTLY ONE. The pool's
            # number is the DISTINCT set of documents (:func:`_aged_receipt_keys`), which is one for
            # one document however many chains carried it; the per-chain field is unchanged.
            "receipts_aged_out": len({k for c in pool for k in _aged_receipt_keys(c)}),
            # WHICH SEAT EACH RENDERED CHAIN TOOK (owner ruling 2026-09-22). The top K are `top`, the
            # sign swap is `sign`, and the three the QUESTION anchors name themselves -- so a reader of
            # the count can tell a page that answered the question's own subject from one that did not.
            "slot_top": sum(1 for c in rendered if c.slot == "top"),
            "slot_sign": sum(1 for c in rendered if c.slot == "sign"),
            "slot_subject": sum(1 for c in rendered if c.slot == "subject"),
            "slot_pair": sum(1 for c in rendered if c.slot == "pair"),
            "slot_horizon": sum(1 for c in rendered if c.slot == "horizon"),
            "state_two_hops": sum(1 for c in pool if c.measured_hops >= 2),
            "with_event": sum(1 for c in pool if c.receipt_kind in ("open", "closed")),
            "with_document": sum(1 for c in pool if c.receipt_kind != "none"),
            "reaching_unnamed": sum(1 for c in pool if c.unnamed_terminal),
            "cross_earned": sum(1 for c in pool if c.cross),
            "curated": sum(1 for c in pool if c.curated),
            "for_side": sum(1 for c in pool if c.side == "for"),
            "against_side": sum(1 for c in pool if c.side == "against"),
            "history_n": [int(c.history.get("n_firings") or 0) for c in rendered],
            # ONE CLOSED WORD PER QUESTION SLOT (CONTRACT C7), stamped by `chain_render_set`'s own
            # branches and carried here verbatim; an empty dict where no selection ran.
            "slot_state": dict(slot_state or {}),
            # THE 09-24 FIX ROUND, at the tail (CONTRACT K13 / K21): how many pool chains carry a premise
            # not in force (none of them seated), and the rank index -- among the rendered chains, in
            # rank order -- of the chain that answers the asked horizon (-1 where none does).
            "premise_off": sum(1 for c in pool if getattr(c, "premise_off", False)),
            "horizon_chain": next((i for i, c in enumerate(sorted(rendered, key=lambda x: x.rank))
                                   if getattr(c, "answers_horizon", False)), -1)}


def _refused_report_key(c: Chain) -> Optional[tuple]:
    """``(contract, driver_id, date)`` of the report sentence a chain's mechanism bound refused, or
    ``None`` -- THE DOCUMENT'S OWN ADDRESS, the key :func:`_aged_receipt_keys` folds actions on. A
    memoised hop carries one refused report into every pool chain that walks it; this is how the count
    line counts it once."""
    d = str(getattr(c, "mechanism_refused_date", "") or "")[:10]
    if not d:
        return None
    hp = getattr(c, "mechanism_refused_hop", None)
    return (str(getattr(hp, "contract", "") or c.contract), str(getattr(hp, "driver_id", "") or ""), d)


# ── the builder ──────────────────────────────────────────────────────────────────────────────────────
def chain_rows(bd: B.Board, graph, *, knobs: B.BoardKnobs, chains=(), spread_fn=None,
               receipts: Optional[dict] = None) -> dict:
    """THE COMPOSED CHAIN LEG. ZERO reads, zero retrievals, zero environment.

    ``ancestor_paths``' own pool (already walked and deduped into ``bd.paths`` at step 6) crossed with
    the EARNED inter-commodity edges of the same board, ranked by :func:`chain_score`, receipted by
    :func:`_chain_receipt`, graded by :func:`chain_history` and cut by :func:`chain_render_set`.

    ``spread_fn`` IS THE RV SEAT, DECLARED AND UNWIRED. On a relative-value question the chain's
    TERMINAL is the PAIR SPREAD's standing rather than the anchor's own front price, and the outcome
    line then reads the SPREAD's move after the firings. ``spread_fn(contract) -> {values, dates,
    unit, scope}`` is the one argument that swaps the basis; the lane that mints the ``pair_spread``
    row passes it and nothing else in this function changes. Absent, the outcome line reads the
    anchor's own tape and names the window it had.

    ``receipts`` IS STEP 5'S OWN MAP (the 09-23 fix round), threaded so each hop's dated document is
    classified over the SAME list step 5 read (:func:`hop_event`); absent, each hop reads its row's own
    step-5 winner, which is every hand-built board's case and HEAD's reading."""
    rows_by_key = {r.key: r for r in bd.rows}
    seat = {k: i for i, k in enumerate(bd.order)}
    named = set(bd.anchor_slugs)
    index = curated_chain_index(chains)
    hop_cache: dict = {}
    hist_cache: dict = {}
    # EACH ANCHOR IS JUDGED ON THE DATA IT HAS (owner ruling 6): its buffer family, its positioning
    # row, its price standing and whether any dated document reached it -- resolved ONCE per contract
    # and read by every candidate chain on it.
    facts: dict = {}

    def _facts(contract):
        got = facts.get(contract)
        if got is None:
            got = anchor_facts(bd, contract)
            facts[contract] = got
        return got

    def _hop(contract, driver_id):
        key = (contract, driver_id)
        got = hop_cache.get(key)
        if got is None:
            row = rows_by_key.get(key)
            got = (chain_hop(bd, row, seat=seat, receipts=receipts) if row is not None
                   else ChainHop(contract=contract, driver_id=driver_id))
            hop_cache[key] = got
        return got

    # THE EARNED-CROSS INDEX. `bd.edges` is MARKET -> MARKET and carries the relation, the sign, the
    # lag and the mechanism, and NO `state_read`; `bd.fan[*].far[*]` is the SAME DRIVER on another
    # board and carries `state_read`, `series_key` and the far confidence. The two are different
    # indexes and only one of them knows what was PRICED, so the composition takes the EDGE from the
    # first and EARNS it against the second. MEASURED on the max fixture: 442 far entries, 82 of them
    # with `state_read` (18.6%) -- that boolean IS "actually priced".
    priced: dict = {}
    for e in bd.fan:
        for f in e["far"]:
            if not f.get("state_read") or not f.get("contract"):
                continue
            cur = priced.get(f["contract"])
            s = seat.get((e["contract"], e["driver_id"]), 10 ** 6)
            if cur is None or s < cur[0]:
                priced[f["contract"]] = (s, f)
    earned: dict = {}
    cross_unpriced = 0
    for e in bd.edges:
        other = str(e.get("other") or "")
        if not other or other == e.get("anchor"):
            continue
        got = priced.get(other)
        if got is None:
            cross_unpriced += 1
            continue
        far = got[1]
        st = bd.series.get(far.get("series_key") or "")
        row = dict(e)
        row["far_driver_id"] = far.get("driver_id") or ""
        row["far_series_key"] = far.get("series_key") or ""
        row["far_level"] = (st.level_shown if st is not None else None)
        row["far_unit"] = (st.unit if st is not None else "")
        row["far_percentile"] = _measure_value(getattr(st, "percentile", None)) if st is not None else None
        earned.setdefault(str(e.get("anchor") or ""), []).append(row)

    # THE FAR BOARD'S ROW OF A SHARED DRIVER, by (near contract, driver id, far contract) -- the index
    # the last link's verdict reads its SAME-DRIVER terminal off (CONTRACT K10, :func:`_terminal_reading`).
    # Built once per board from the fan the walk already named; zero reads.
    far_index: dict = {}
    for e in bd.fan:
        for f in e["far"]:
            if f.get("contract"):
                far_index.setdefault((e["contract"], e["driver_id"], f["contract"]), f)

    pool: list = []
    single_hop_paths = 0
    series_folded = 0
    composed: set = set()
    for p in bd.paths:
        contract = p["contract"]
        hop_ids = tuple(p.get("hops") or ())
        if len(hop_ids) < 2:
            # A PATH TOO SHORT TO COMPOSE IS COUNTED (round-2 census blocker 7, carried). A chain is
            # a SEQUENCE and one hop is not one; the path is not a chain and never becomes one -- but
            # it was on the board, the count line's `total` is the pool and not the paths, and a drop
            # nothing records is the shape this movement's own doctrine forbids. It rides the count
            # line under its own name (`single_hop_paths`), declared in :data:`CHAIN_SEAM_FIELDS`,
            # beside `cross_unpriced` -- the other fact the BUILDER knows and the selection cannot.
            single_hop_paths += 1
            continue
        # ONE SERIES, ONE LINK (CONTRACT K12). Consecutive hops reading ONE series fold into one link
        # before anything is scored, so no agreement is ever computed between a series and itself and
        # the chain's depth is the number of REAL links. A path the fold leaves with one link is not a
        # chain (counted as `single_hop_paths`); a path the fold makes identical to a sequence already
        # composed is that chain (counted, never composed twice). Every folded path is counted.
        hops, n_fold = fold_series_hops(tuple(_hop(contract, h) for h in hop_ids))
        if n_fold:
            series_folded += 1
        if len(hops) < 2:
            single_hop_paths += 1
            continue
        seq = (contract, tuple(h.driver_id for h in hops))
        if n_fold and seq in composed:
            continue
        composed.add(seq)
        af = _facts(contract)
        base = _compose(bd, hops, contract=contract, index=index, named=named,
                        hist_cache=hist_cache, anchor=af, far_index=far_index)
        pool.append(base)
        # ONE FULL COMPOSITION PER PATH, AND A DERIVATION PER EARNED CROSS. Every term but REACH is a
        # fact of the HOPS, and the hops are identical across a path's cross variants -- so composing
        # each variant from scratch recomputed the same tail, the same receipt, the same record and
        # the same confidence once per priced far market. MEASURED: 2,494 ms for the 1,848 candidate
        # chains of the max fixture board, against a stage 2 whose whole wall is 108 ms.
        for e in earned.get(contract, ()):
            pool.append(_with_cross(bd, base, e, index=index, named=named, hist_cache=hist_cache,
                                    anchor=af, far_index=far_index))

    # THE THREE SEATS THE QUESTION ANCHORS (owner ruling 2026-09-22), read off the board the planner
    # already resolved -- NO new detection. The SUBJECT ids are `Board.subject_ids_on` (the anchor's
    # own driver plus the group members THIS board carries) plus the `attached_event` anchor's driver,
    # which is the gesture that outranks every inference and is not a `DRIVER_ANCHOR_SOURCES` word.
    # The PAIR markets are the ones the question NAMED (`Anchor.named` is monotonic across the
    # precedence collapse -- "once named, always named" -- so a board reached twice is still named).
    subject_ids: dict = {}
    explicit_ids: dict = {}
    for slug in bd.anchor_slugs:
        ids = set(bd.subject_ids_on(slug))
        for a in bd.anchors:
            if a.contract == slug and a.source == "attached_event" and a.driver_id:
                ids.add(str(a.driver_id))
            if a.contract == slug and a.source in ("attached_event", "focus_driver") and a.driver_id:
                explicit_ids.setdefault(slug, set()).add(str(a.driver_id))
        if ids:
            subject_ids[slug] = frozenset(ids)
    # THE SUBJECT'S STANDING IN THE QUESTION'S REACH (CONTRACT K9, OWNER DECISION O-5), stamped at stage 2
    # by :func:`subject_standing`. On a SINGLE-MARKET question a pick the question's own words did not
    # name -- a SEMANTIC-tier pick, exact [] and alias [] across its group -- does not seat: its ids leave
    # the slot's test (never the anchor set, never a row) and the slot reads `not_asked` where nothing
    # lexical is left. A pick with no carrier in reach leaves the slot `no_candidate`.
    standing = dict(getattr(bd, "subject_reach", None) or {})
    tiers = dict(standing.get("tiers") or {})
    members = _pick_members(bd)
    subject_off = subject_slot_off_word(bd)
    if standing:
        lexical: set = set()
        semantic: set = set()
        for p, t in tiers.items():
            (semantic if t == "semantic" else lexical).update(members.get(p, {p}))
        semantic_only = semantic - lexical
        if standing.get("single_market") and semantic_only:
            had = bool(subject_ids)
            for slug in list(subject_ids):
                keep = frozenset(i for i in subject_ids[slug]
                                 if i not in semantic_only or i in explicit_ids.get(slug, set()))
                if keep:
                    subject_ids[slug] = keep
                else:
                    del subject_ids[slug]
            if had and not subject_ids:
                # a LEXICAL pick was asked and nothing on the page can answer it; with none, not asked
                subject_off = "no_candidate" if lexical else "not_asked"
        if tiers and len(standing.get("declined_picks") or ()) == len(tiers):
            subject_off = "no_candidate"
        if standing.get("single_market") and tiers and not lexical:
            # O-5: the question's own words named no driver -- the slot is not asked, whatever the draw
            # (the trace still carries every pick, its tier and any decline).
            subject_off = "not_asked"
    # THE DISTANCE-0 SET (K9): a subject chain must run on, or into, one of the question's own markets.
    question_markets = (frozenset(s for s, d in (getattr(bd, "question_reach", ()) or ()) if int(d) == 0)
                        or None)
    named_contracts = tuple(a.contract for a in bd.anchors
                            if getattr(a, "named", False) or a.source == "named")
    out = chain_render_set(pool, k=int(getattr(knobs, "chain_render_k", 0) or 0),
                           print_line=float(getattr(knobs, "chain_print_line", 40) or 40),
                           subject_ids=subject_ids, named_contracts=named_contracts,
                           horizon_months=bd.horizon_months,
                           subject_off=subject_off, question_markets=question_markets)
    out["counts"]["cross_unpriced"] = cross_unpriced
    out["counts"]["single_hop_paths"] = single_hop_paths
    out["counts"]["series_folded"] = series_folded
    # THE LEXICAL TIER EACH SUBJECT CHAIN CARRIES (O-5), for the seat's label: the best tier among the
    # picks whose group ids this chain's hops carry on its own contract.
    if tiers:
        for c in pool:
            if "subject" not in (c.slot_fits or ()):
                continue
            carried = set(c.hop_ids) | {a for h in c.hops for a in (h.aliases or ())}
            carried &= set(subject_ids.get(c.contract) or ())
            best = [tiers[p] for p in tiers if members.get(p, {p}) & carried]
            c.subject_tier = min(best, key=lambda t: _TIER_ORDER.get(t, 9)) if best else ""
    # THE SENTENCES AND THE OUTCOME LINE ARE BUILT FOR THE CHAINS A READER OR A PAYLOAD MEETS, and for
    # no others. Neither is a rank term -- the arithmetic that DECIDED the selection ran on every
    # candidate -- so building either for a pool of two thousand would be prose nobody reads. The
    # outcome line is the base rate a reader is handed AFTER the selection (owner ask, 2026-09-17).
    for c in out["rendered"]:
        chain_explain(c, named_markets=named, horizon_months=bd.horizon_months,
                      anchor=_facts(c.contract))
        c.outcome = _outcome_for(bd, c, spread_fn=spread_fn)
    for c in chain_trace_set(pool):
        if not c.notes:
            chain_explain(c, named_markets=named, horizon_months=bd.horizon_months,
                          anchor=_facts(c.contract))
    out["pool"] = pool
    return out


#: THE THREE LEXICAL TIERS OF A SUBJECT PICK, strongest first (CONTRACT K9, O-5).
SUBJECT_TIERS: tuple = ("exact", "alias", "semantic")
_TIER_ORDER: dict = {t: i for i, t in enumerate(SUBJECT_TIERS)}


def _pick_members(bd) -> dict:
    """``{pick: set(group ids)}`` -- each pick with the group the seam already expanded it to
    (``Board.subject["groups"]``), the pick alone where no group rode the payload."""
    sub = dict(getattr(bd, "subject", None) or {})
    groups = dict(sub.get("groups") or {})
    out: dict = {}
    for p in (sub.get("picked") or ()):
        p = str(p)
        out[p] = {p} | {str(i) for i in (groups.get(p) or ()) if str(i or "").strip()}
    return out


def subject_standing(bd, graph) -> dict:
    """**THE SUBJECT'S STANDING IN THE QUESTION'S REACH** (CONTRACT K9, OWNER DECISION O-5) -- the dict the
    walk stamps on :attr:`board.Board.subject_reach` at stage 2, or ``{}`` where the resolver did not
    reach the turn (no ``Board.subject``) or no reach was computed. ZERO reads.

      ``tiers``          ``{pick: exact | alias | semantic}``: the STRONGEST free tier (the resolver's
                         own ``hints.exact`` / ``hints.alias``) that matched ANY id of the pick's group
                         -- the group is the synonym set the pick expanded to, so the question's words
                         naming one spelling of it names the pick. A pick no free tier matched is an
                         inference (``semantic``), whatever the planner made of it.
      ``declined_picks`` the picks whose group has NO carrier on any board of the reach; where that is
                         every pick, ``declined`` reads ``not_on_question_markets`` and the subject slot
                         ``no_candidate`` -- a visible decline, never a silent one (W-4).
      ``single_market``  the question's own markets (distance 0) are ONE: O-5's condition for a semantic
                         pick not seating."""
    sub = dict(getattr(bd, "subject", None) or {})
    reach = tuple(getattr(bd, "question_reach", ()) or ())
    if not sub or not reach:
        return {}
    hints = dict(sub.get("hints") or {})
    exact = {str(i) for i in (hints.get("exact") or ())}
    alias = {str(i) for i in (hints.get("alias") or ())}
    members = _pick_members(bd)
    tiers: dict = {}
    declined: list = []
    boards = [s for s, _d in reach]
    for p, ids in members.items():
        tiers[p] = "exact" if ids & exact else ("alias" if ids & alias else "semantic")
        if not any(_driver_of(graph, s, i) is not None for s in boards for i in sorted(ids)):
            declined.append(p)
    # FIXER PASS (REVIEW_WT MAJOR-5): O-5 IS A RULING ON A SINGLE-MARKET QUESTION -- the markets the
    # question's own words gave (a NAMED anchor, or the attached event's), never the planner's inferred
    # seeds (distance 0 carries every `sg.seeds` contract, so an LLM planner that inferred a second seed
    # decided the ruling). Where the words named no market at all, the distance-0 count stands in.
    own = {str(a.contract) for a in (getattr(bd, "anchors", ()) or ())
           if getattr(a, "named", False) or str(getattr(a, "source", "") or "") in ("named", "attached_event")}
    single = (len(own) == 1) if own else (sum(1 for _s, d in reach if int(d) == 0) == 1)
    return {"tiers": tiers, "declined_picks": declined,
            "single_market": single,
            "declined": ("not_on_question_markets" if members and len(declined) == len(members)
                         else "")}


def fold_series_hops(hops) -> tuple:
    """``(hops, n_folded)`` -- a composed path with every run of CONSECUTIVE hops that read ONE series
    folded into ONE link (CONTRACT K12, the 09-24 re-smoke's item 21).

    THE KEY IS :attr:`ChainHop.fold_key` -- the same key the diversity rule folds whole chains on (one
    series, one reading, one spelling), so a hop with no series (its own ``(contract, driver_id)``) never
    folds into its neighbour. The link keeps the FIRST node's identity and declaration (its id names the
    chain, its sign carries the chain's declared direction) and records every folded node on
    :attr:`ChainHop.aliases`. A folded node's dated document is not lost: where the link itself carries
    none and the folded node does, the node's document rides the link, and its report sentences join
    the link's own. Nothing is scored here and nothing is removed from the board."""
    out: list = []
    n = 0
    for h in hops or ():
        # ONE READING UNDER ANY OF ITS NAMES (the 09-25 fix round, W-3 / N7): the series key, or the
        # measured quantity two cards serve under two keys (:attr:`ChainHop.reading_keys`).
        if out and (h.fold_key == out[-1].fold_key or (h.reading_keys & out[-1].reading_keys)):
            out[-1] = _fold_into(out[-1], h)
            n += 1
            continue
        out.append(h)
    return tuple(out), n


def _fold_into(a: ChainHop, b: ChainHop) -> ChainHop:
    """ONE link from two consecutive hops on one series: ``a``'s identity, ``b``'s id kept as an alias,
    ``b``'s dated document carried where ``a`` has none (see :func:`fold_series_hops`)."""
    kw: dict = {"aliases": tuple(a.aliases or ()) + (b.driver_id,) + tuple(b.aliases or ())}
    if str(a.event_kind or "none") in ("", "none") and str(b.event_kind or "none") not in ("", "none"):
        kw.update(event_date=b.event_date, event_precision=b.event_precision, event_open=b.event_open,
                  event_receipt=b.event_receipt, event_kind=b.event_kind,
                  event_interval=b.event_interval)
    seen = {str((r or {}).get("text") or "") for r in (a.receipts_top or ()) if isinstance(r, dict)}
    extra = tuple(r for r in (b.receipts_top or ())
                  if isinstance(r, dict) and str(r.get("text") or "") not in seen)
    if extra:
        kw["receipts_top"] = tuple(a.receipts_top or ()) + extra
    return replace(a, **kw)


def subject_slot_off_word(bd) -> str:
    """THE SUBJECT SLOT'S WORD WHEN NO SUBJECT ID REACHED THE POOL (CONTRACT C7, W-1), read off the
    BOARD and never off a flag. ``Board.subject`` is written by the seam ONLY when the resolver payload
    is on (``seam._stamp_subject`` returns early otherwise), so an empty dict is exactly "the resolver
    never ran" -- ``resolver_off`` -- and a non-empty one is a resolver that ran: ``not_asked`` when it
    picked nothing, ``no_candidate`` when it picked ids no anchor board of this turn carries (the
    anchor ceiling can cut every subject board). A ``focus_driver`` or ``attached_event`` anchor makes
    the slot LIVE, and a live slot's word is the selection's own (:func:`chain_render_set`)."""
    sub = getattr(bd, "subject", None) or {}
    if not sub:
        return "resolver_off"
    return "no_candidate" if (sub.get("picked") or ()) else "not_asked"


#: How many chains the TRACE carries. The POOL is whole in memory and whole in the count line; the
#: PAYLOAD is bounded, because a max board composes 1,848 candidates and a `state_board` record
#: carrying two thousand chain rows would be an instrument nobody can open. The rendered chains come
#: first and the rest are the next best by rank, so the payload always answers "what did it render,
#: and what was it beaten by".
CHAIN_TRACE_K: int = 12


def chain_trace_set(chains, k: int = 0) -> list:
    """The bounded chain payload: everything RENDERED first, then the best candidate of every LIVE
    question slot, then the next best by rank -- ONE chain per DISTINCT hop sequence.

    **THE 09-23 RE-SMOKE's TARIFF PAYLOAD WAS TWO RENDERED CHAINS AND TEN CROSS-VARIANTS OF ONE
    SEQUENCE** (crude -> crush -> stocks-to-use, reaching ten different priced far markets), so the one
    question a banked payload exists to answer -- "what did it render, and what was it beaten by" --
    had one answer ten times, and the China tariff chains the subject slot exists for were not on it.
    The fill now takes (1) every rendered chain, whatever it shares; (2) for each LIVE question slot
    (:attr:`Chain.slot_fits`, stamped by :func:`chain_render_set`'s own slot tests) the best-ranked
    chain answering it that is not already carried, with its ``decline`` word on its row; (3) the
    rest by rank, SKIPPING a chain whose ``(contract, hop_ids)`` sequence is already carried -- a cross
    variant is the same path reaching another market, and its score, receipt and record are the path's.
    The cap is :data:`CHAIN_TRACE_K`; raising it was the rejected fix."""
    k = int(k or CHAIN_TRACE_K)
    pool = sorted(chains or (), key=lambda c: c.rank)
    out = [c for c in pool if c.rendered]
    taken = {id(c) for c in out}
    seqs = {(c.contract, c.hop_ids) for c in out}
    for word in QUESTION_SLOTS:
        if len(out) >= k:
            break
        best = next((c for c in pool if id(c) not in taken and word in (c.slot_fits or ())
                     and (c.contract, c.hop_ids) not in seqs), None)
        if best is not None:
            out.append(best)
            taken.add(id(best))
            seqs.add((best.contract, best.hop_ids))
    for c in pool:
        if len(out) >= k:
            break
        if id(c) in taken or (c.contract, c.hop_ids) in seqs:
            continue
        out.append(c)
        taken.add(id(c))
        seqs.add((c.contract, c.hop_ids))
    return out


def _compose(bd, hops, *, contract, index, named, hist_cache, anchor=None,
             far_index=None) -> Chain:
    """ONE INTRA-DAG composed chain, scored, with NO cross hop. The hops are SHARED objects."""
    ch = Chain(contract=contract, asof=str(getattr(bd, "asof", "") or ""), hops=hops,
               depth=len(hops) - 1, terminal=contract, cross=None)
    ch.curated = _curated_for(index, contract, ch.hop_ids)
    _agree(bd, ch, cross=None, far_index=far_index)
    # THE RECEIPT HOP IS CHOSEN BEFORE THE SCORE, because the HISTORY term is read at THAT hop and the
    # score needs the history. One rule, stated once, read by both (`chain_score` re-derives the same
    # index from the same tuple and `test_state_walk` pins that the two agree).
    ch.receipt_index = chain_receipt_index(hops)
    return chain_score(ch, named_markets=named, horizon_months=bd.horizon_months,
                       history=_history(bd, ch, hist_cache), with_notes=False, anchor=anchor)


def _with_cross(bd, base: Chain, cross: dict, *, index, named, hist_cache, anchor=None,
                far_index=None) -> Chain:
    """The same hops carried onto ONE earned far market. EVERY TERM BUT REACH IS A FACT OF THE HOPS.

    ``tail``, ``event``, ``asymmetry``, ``confidence`` and ``lag`` read only the hops, and so does
    ``history`` UNLESS the receipt hop is the last one -- in which case the record is read against the
    FAR reading and is genuinely a different number, so it is recomputed (and memoised on the far
    series key like every other pair). What the cross changes is the REACH term, the terminal, the
    chain's declared direction and the last agreement."""
    ch = Chain(contract=base.contract, asof=base.asof, hops=base.hops, depth=base.depth, cross=cross,
               terminal=str(cross.get("other") or base.contract),
               terminal_level=cross.get("far_level"),
               terminal_unit=cross.get("far_unit") or "",
               terminal_percentile=cross.get("far_percentile"),
               receipt_index=base.receipt_index, receipt=base.receipt,
               receipt_kind=base.receipt_kind, receipt_words=base.receipt_words,
               # THE AGED-OUT COUNT IS A FACT OF THE HOPS, and the hops are identical across a path's
               # cross variants -- so it rides the derivation exactly as the receipt it belongs to
               # does. Without it a cross variant of a chain that HAD a receipt would report zero
               # aged-out documents while its own base reported one. The HOP it sits on and its DATE
               # ride with it for the same reason (census 4): they are facts of the same hops.
               receipts_aged_out=base.receipts_aged_out,
               aged_receipt_hop=base.aged_receipt_hop, aged_receipt_date=base.aged_receipt_date,
               # THE EVENT WORD IS A FACT OF THE SAME HOPS (the 09-23 fix round) and rides with the
               # receipt it names, exactly as the aged-out count does.
               event_kind=base.event_kind,
               # AND SO IS THE REPORT THE MECHANISM BOUND REFUSED (the 09-25 fix round, W-4 / N12): the
               # base chain computed it off these very hops, and the variant's `chain_score` skips
               # `_chain_receipt` (the receipt is copied), so without this the variant's trace row read
               # an empty refused pair beside its base's "crude_oil 2005-09-01" (max chain 2 vs 5).
               # `chain_counts["mechanism_refused"]` folds on the document's own key, so the count is
               # unchanged.
               mechanism_refused_hop=base.mechanism_refused_hop,
               mechanism_refused_date=base.mechanism_refused_date)
    ch.terminal_key = ((ch.terminal, cross.get("far_driver_id") or "")
                       if cross.get("far_driver_id") else None)
    ch.curated = base.curated or _curated_for(index, base.contract, base.hop_ids,
                                              cross_other=ch.terminal)
    _agree(bd, ch, cross=cross, base=base, far_index=far_index)
    hist = (base.history if ch.receipt_index + 1 < len(ch.hops)
            else _history(bd, ch, hist_cache))
    return chain_score(ch, named_markets=named, horizon_months=bd.horizon_months, history=hist,
                       with_notes=False, anchor=anchor)


def _agree(bd, ch: Chain, *, cross: Optional[dict], base: Optional[Chain] = None,
           far_index: Optional[dict] = None) -> None:
    """The per-hop DECLARED relative sign and the AGREEMENT today's readings show for it.

    ``agreements[i]`` is the verdict for hop ``i`` onto hop ``i+1``; the LAST entry is the verdict onto
    the TERMINAL -- the anchor's own price where no cross was earned (HEAD's reading: the hop's own
    declared sign, never measured, so ``undetermined``), and the FAR MARKET where one was. A chain is
    never ranked down for a disagreement: the verdict is a FIELD, and :attr:`Chain.against_hops` is what
    the block names in its one disagreement line.

    **THE LAST LINK ONTO A FAR MARKET READS THAT MARKET, OR IT SETTLES NOTHING** (CONTRACT K10, the
    09-24 re-smoke's item 16). HEAD signed the last hop's move against ``cross["far_series_key"]`` -- the
    far board's best-seated SHARED driver, whichever one EARNED the cross -- under the market-to-market
    sign: 17 of 25 rendered chains carried a verdict made that way (10 of them "at odds"), e.g. the US
    soybean stocks-to-use move signed against China's beginning stocks ("the last link, from that ratio
    onto the Dalian soybean contract, runs against") and blended fertilizer against the ONI ("the last
    link into corn runs against it"). :func:`_terminal_reading` now names the ONE reading the verdict
    reads -- the far contract's own tape, else the far board's row of the SAME driver as the last hop,
    else nothing (``undetermined``) -- and the earned cross stays a REACH fact.

    **AND THE LAST LINK'S DECLARED RELATION IS THE COMPOSED ONE.** The cross edge's sign is how the
    ANCHOR market moves the far one; the last hop moves the anchor by its own declared sign; so the
    relation between the last hop and the far market is the PRODUCT of the two -- the same telescoping
    :func:`chain_declared_sign` states for the whole chain. HEAD stored the cross sign alone as the last
    link's relation, so the page told a reader the model expects the US stocks-to-use ratio to move the
    Dalian contract "in the opposite direction" when the model's own two declarations compose to "the
    same direction". A far board's same-driver row is related to the last hop through that product
    times the far board's own declared sign for the driver.

    **AND A PREMISE NOT IN FORCE IS STAMPED HERE** (CONTRACT K13), beside the direction it unsettles:
    :func:`_premise_off` over the chain's first hop."""
    hops = ch.hops
    if base is not None:
        signs, verdicts = list(base.edge_signs[:-1]), list(base.agreements[:-1])
        i = len(hops) - 1
    else:
        signs, verdicts, i = [], [], 0
    ch.terminal_reading = {}
    while i < len(hops):
        nxt = hops[i + 1] if i + 1 < len(hops) else None
        if nxt is None:
            es = str(hops[i].sign or "")
            vs = es
            child_move = 0.0
            if cross is not None:
                tr = _terminal_reading(bd, hops[i], cross, far_index)
                ch.terminal_reading = {k: tr[k] for k in ("source", "series_key", "sign")}
                es = composed_sign(hops[i].sign, str(cross.get("sign") or ""))
                vs = str(tr["sign"])
                # THE ONE PREDICATE (09-25 close-out, RW-2 / N8): the far market's own move is read here
                # exactly where `chain_score`'s reach note says "whose own move this record reads" -- both
                # read :func:`terminal_read`, over the one reading `_terminal_reading` returned.
                child_move = _newest_move(tr["state"]) if terminal_read(tr) else 0.0
        else:
            es = hop_edge_sign(hops[i].sign, nxt.sign)
            vs = es
            child_move = _hop_move(nxt)
        signs.append(es)
        verdicts.append(ST.sign_agreement(_hop_move(hops[i]), child_move, vs).get("value"))
        i += 1
    ch.edge_signs = tuple(signs)
    ch.agreements = tuple(verdicts)
    ch.against_hops = tuple(hops[j].driver_id for j, v in enumerate(verdicts) if v == "at_odds")
    ch.declared_sign = chain_declared_sign(hops, cross_sign=str((cross or {}).get("sign") or ""))
    ch.premise_off = _premise_off(hops[0]) if hops else False
    ch.direction, ch.side = _chain_direction(ch)


def _premise_off(top) -> bool:
    """IS THE CHAIN'S PREMISE A PHASE NOT IN FORCE? (CONTRACT K13) -- the first hop names one pole of a
    DECLARED phase pair (``state_conventions.yaml`` ``phase_pairs``, read through :func:`hop_phase`, the
    one phase producer) and that pole is NOT the one the reading puts in force: ``ChainHop.phase_in_force
    is False``. That is the other pole in force (La_Nina at ONI +1.8 -- max chain 3) AND the reading
    inside the line, where neither pole is in force (IOD at -0.11 degC against its 0.4 band -- soyoil's
    IOD_positive subject seat, the brief's own proof): a chain arguing a phase's effects has no premise
    while that phase is not happening. A first hop on no declared pair (``phase_in_force is None``) is
    never off, and a hop whose state could not be read is never off. Nothing here names an id.

    (The round-1 TAIL re-orientation is a different rule and is untouched: inside the line the reading
    is neither phase's, so its unsigned distance scores as HEAD scored it -- W-7. What changes here is
    only whether the chain's PREMISE stands.)"""
    pd = str(getattr(top, "phase_driver", "") or "")
    return bool(pd) and getattr(top, "phase_in_force", None) is False


#: THE ONE ``source`` WORD :func:`_terminal_reading` STAMPS WHERE THE LAST LINK READ NO SERIES ON THE FAR
#: MARKET -- its third rung, and the ONLY rung whose ``state`` is ``None``. Declared once: the producer writes
#: it and :func:`terminal_read` tests it (the 09-25 close-out, RW-2 / N8).
TERMINAL_UNREAD: str = "undetermined"


def terminal_read(reading) -> bool:
    """IS THE FAR MARKET'S OWN MOVE READABLE ON THIS TURN? -- does the last link's terminal reading carry a
    READ SERIES (the 09-25 close-out, RW-2; the owner's N8 ruling of 2026-09-25).

    ONE PREDICATE, TWO READERS: :func:`_agree` reads it to decide whether the verdict's child move is the far
    reading's newest move, and :func:`chain_score`'s reach NOTE reads it to say whether this record reads the
    own move of a market the question did not name -- WORDS ONLY: the N8 split that paid five of the reach
    points on it was restored to the banked arithmetic on 2026-09-25 after measurement (the owner's ruling:
    an unread far market never loses reach credit; a read one may earn extra once far reads land). It reads
    the ``source`` the one producer (:func:`_terminal_reading`) stamped: ``tape`` and ``same_driver`` are the
    two rungs that return a state, :data:`TERMINAL_UNREAD` the one that returns ``None`` -- so on the reading
    that producer returns this is exactly "the reading's state is not None", and it stays answerable on the
    reading the chain keeps (``Chain.terminal_reading``, which carries no object -- A.7). An EMPTY reading (a
    chain with no cross hop, whose terminal verdict is HEAD's never-measured one) reads nothing."""
    src = str((reading or {}).get("source") or "")
    return bool(src) and src != TERMINAL_UNREAD


def _terminal_reading(bd, last, cross: dict, far_index: Optional[dict] = None) -> dict:
    """THE ONE READING THE LAST LINK'S VERDICT READS, onto a far market (CONTRACT K10) --
    ``{"source", "state", "series_key", "sign"}``, in this order, ZERO reads:

      1. ``tape`` -- the far contract's OWN front-price tape, where this board read it (``bd.tape`` is
         keyed by ANCHOR slug, so a far market carries one exactly when the question also anchored it:
         the pair turns). ``sign`` = the last hop's declared sign times the cross edge's -- the relation
         between the last hop and the far PRICE;
      2. ``same_driver`` -- the far board's row of the SAME driver id as the last hop: the far anchor's
         own row where the far market is an anchor, else the fan's far entry for that driver whose
         series this turn actually read (``bd.series``). ``sign`` = that relation times the far board's
         own declared sign for the driver. A far row reading the last hop's OWN series is the series
         against itself -- an identity, not a verdict -- and reads ``undetermined`` (K12's rule, one
         link over);
      3. ``undetermined`` -- neither was read; ``state`` is None and the verdict is
         ``stats.sign_agreement``'s own ``undetermined``.

    The earned cross's far reading (``cross["far_series_key"]``) is NEVER read here: it is whichever
    shared driver first earned the cross -- China's beginning stocks for a US stocks-to-use hop, the ONI
    for a fertilizer hop -- and a verdict against it is a verdict against an unrelated reading."""
    far = str((cross or {}).get("other") or "")
    link = composed_sign(getattr(last, "sign", ""), str((cross or {}).get("sign") or ""))
    tp = (getattr(bd, "tape", None) or {}).get(far) if far else None
    # A TAPE THE BOARD READ, AS THE VERDICT NEEDS IT (FIXER PASS, REVIEW_WT lexical): the tape carries a
    # non-declined change window -- the one fact `_newest_move` reads for the verdict -- never a typed
    # subset of its status words. A slug with no tape, a pre-coverage as-of or a declined front read carries
    # no price move at all and falls through to the same-driver row.
    if tp is not None and _has_move(tp):
        return {"source": "tape", "state": tp, "series_key": "tape|%s" % far, "sign": link}
    did = str(getattr(last, "driver_id", "") or "")
    own = str(getattr(last, "series_key", "") or "")
    st, sk, far_sign = None, "", ""
    frow = bd.row(far, did) if (far and did and far in set(getattr(bd, "anchor_slugs", ()) or ())) else None
    if frow is not None and frow.state is not None and status_word(frow.state.status) == "ok":
        st, sk, far_sign = frow.state, str(frow.series_key or ""), str(frow.sign or "")
    else:
        f = (far_index or {}).get((str(getattr(last, "contract", "") or ""), did, far))
        if f is not None:
            k = str(f.get("series_key") or f.get("far_key") or "")
            got = (getattr(bd, "series", None) or {}).get(k) if k else None
            if got is not None and status_word(got.status) == "ok":
                st, sk, far_sign = got, k, str(f.get("sign") or "")
    if st is None or (own and sk == own):
        return {"source": TERMINAL_UNREAD, "state": None, "series_key": sk, "sign": ""}
    return {"source": "same_driver", "state": st, "series_key": sk,
            "sign": composed_sign(link, far_sign) if link else ""}


def _pole_absent(hp) -> bool:
    """A hop that names one pole of a declared phase pair while the OTHER pole is in force, and whose
    own pole carries NO reading -- neither the latest print nor any reading inside its declared window
    sits on its side (:attr:`ChainHop.phase_reoriented` with a zero :attr:`ChainHop.chain_tail`). Its
    series is moving, but the move is the other pole's: for DIRECTION it is read as an unmeasured hop
    (W-7). A hop whose own-pole reading is still in its window keeps HEAD's reading."""
    return bool(getattr(hp, "phase_reoriented", False)) and float(getattr(hp, "chain_tail", 0.0)) == 0.0


def _hop_move(hp) -> float:
    """The hop's move TODAY for the agreement verdict -- HEAD's ``ChainHop.move``, and 0.0 (which
    `stats.sign_agreement` reads as ``undetermined``, never as flat) for a hop whose pole is absent
    (:func:`_pole_absent`): a pole not in force cannot agree or run against its neighbour."""
    return 0.0 if _pole_absent(hp) else float(getattr(hp, "move", 0.0) or 0.0)


def _history(bd, ch: Chain, hist_cache: dict) -> dict:
    """:func:`_history_for`, memoised on the HOP PAIR -- the arithmetic does not depend on the chain.

    THE TERMINAL HALF OF THE KEY IS THE READING THE VERDICT READ (CONTRACT K10), never the earned
    cross's far driver: two cross variants onto one far market read one terminal, and a variant onto a
    market whose terminal settles nothing shares nothing with one that read a tape."""
    i = ch.receipt_index
    if i + 1 < len(ch.hops):
        nxt_key = ch.hops[i + 1].key
    elif ch.cross:
        tr = ch.terminal_reading or {}
        nxt_key = ("terminal", ch.terminal, str(tr.get("source") or ""),
                   str(tr.get("series_key") or ""))
    else:
        nxt_key = ch.terminal_key
    hkey = (ch.hops[i].key, nxt_key, str(ch.edge_signs[i] if i < len(ch.edge_signs) else ""),
            str((ch.terminal_reading or {}).get("sign") or "") if (i + 1 >= len(ch.hops)) else "")
    hist = hist_cache.get(hkey)
    if hist is None:
        hist = _history_for(bd, ch)
        hist_cache[hkey] = hist
    return hist


def _history_for(bd, ch: Chain) -> dict:
    """The receipt hop's own record against the hop BELOW it (or the TERMINAL READING where it is last).

    THE TERMINAL BRANCH READS THE SAME READING THE LAST LINK'S VERDICT READ (CONTRACT K10): the far
    contract's own tape (its served bundle, read by value exactly as :func:`_outcome_for` reads the
    anchor's), the far board's row of the same driver, or nothing -- under the relation that verdict was
    taken under. HEAD read ``cross["far_series_key"]``, the unrelated shared driver that earned the
    cross, so the record line under a terminal link counted the wrong series' moves."""
    i = ch.receipt_index
    parent = ch.hops[i]
    prow = bd.row(parent.contract, parent.driver_id)
    pst = prow.state if prow is not None else None
    sign = str(ch.edge_signs[i] if i < len(ch.edge_signs) else "")
    if i + 1 < len(ch.hops):
        crow = bd.row(ch.hops[i + 1].contract, ch.hops[i + 1].driver_id)
        cst = crow.state if crow is not None else None
    elif ch.cross:
        tr = ch.terminal_reading or {}
        src = str(tr.get("source") or "")
        sign = str(tr.get("sign") or "")
        if src == "tape":
            cst = _tape_series(bd, ch.terminal)
        elif src == "same_driver":
            cst = bd.series.get(str(tr.get("series_key") or ""))
            if cst is None:
                frow = bd.row(ch.terminal, parent.driver_id)
                cst = frow.state if frow is not None else None
        else:
            cst = None
    else:
        cst = None
    direction = 1 if parent.run_direction == "up" else (-1 if parent.run_direction == "down" else 0)
    return chain_history(pst, cst, edge_sign=sign, band=parent.lag_band, asof=bd.asof,
                         direction=direction)


def _tape_series(bd, slug: str):
    """A far market's TAPE as the one shape :func:`chain_history` reads -- a :class:`StateRow` whose
    ``inputs`` carry the tape's own served bundle under its own label -- or ``None``. ZERO reads: the
    bundle is the one the tape read already returned (``TapeState.inputs``), read by VALUE exactly as
    :func:`_outcome_for` reads the anchor's own tape. Nothing is recomputed; the array is the record."""
    tp = (getattr(bd, "tape", None) or {}).get(slug)
    if tp is None:
        return None
    from leviathan.graphrag.state.rows import SeriesKey
    for arr in (getattr(tp, "inputs", None) or {}).values():
        if (arr or {}).get("values"):
            key = SeriesKey(ref="tape", commodity=str(slug))
            return StateRow(key=key, status="ok", cadence="daily",
                            asof=str(getattr(tp, "asof", "") or getattr(bd, "asof", "") or ""),
                            inputs={key.label(): dict(arr)})
    return None


def _outcome_for(bd, ch: Chain, *, spread_fn=None) -> dict:
    """The anchor's own price move after each of the receipt hop's past firings -- or the honest line
    that says the price array does not reach them."""
    firings = list((ch.history or {}).get("firings") or ())
    band = ch.hops[ch.receipt_index].lag_band if ch.hops else None
    vals, dates, unit, scope = (), (), "", ""
    if spread_fn is not None:
        try:
            got = spread_fn(ch.contract) or {}
        except Exception:                               # noqa: BLE001 -- a seam must never kill a turn
            got = {}
        vals, dates = tuple(got.get("values") or ()), tuple(got.get("dates") or ())
        unit, scope = str(got.get("unit") or ""), str(got.get("scope") or "")
    if not vals:
        # `bd.tape` IS KEYED BY ANCHOR SLUG ONLY and a `TapeState` is not a `StateRow` -- it carries no
        # `SeriesKey`, so its bundle is read by VALUE rather than by key. MEASURED: one entry on a
        # one-anchor board, `{slug|contract_month: {values, dates, unit}}`, ~320 sessions.
        tp = (bd.tape or {}).get(ch.contract)
        for arr in (getattr(tp, "inputs", None) or {}).values():
            from leviathan.graphrag.state import transforms as TR
            v, d, _n = TR.dated_pairs((arr or {}).get("values"), (arr or {}).get("dates"))
            if v:
                vals, dates, unit = tuple(v), tuple(d), str((arr or {}).get("unit") or "")
                break
        if dates:
            scope = "the front price's own %s to %s window" % (str(dates[0])[:10], str(dates[-1])[:10])
    return chain_outcome(list(vals), list(dates), unit=unit, firings=firings, band=band,
                         declared_sign=ch.declared_sign, scope=scope)


def _chain_direction(ch: Chain) -> tuple:
    """``(direction, side)`` -- what this chain implies for the anchor TODAY, in two vocabularies.

    ``direction`` is ``higher`` / ``lower`` / ``unsettled`` and ``side`` is the owner's own words for
    the same fact (``for`` / ``against`` / ``unsettled``), so the render can speak either. A chain is
    UNSETTLED when the graph declines to declare a sign anywhere on it, when its top reading is not
    moving, or when ANY hop runs against the direction the graph declares for it -- and being
    unsettled costs the chain nothing in the rank, because disagreement is information."""
    if not ch.declared_sign or not ch.hops:
        return ("unsettled", "unsettled")
    if ch.against_hops:
        return ("unsettled", "unsettled")
    # A PREMISE NOT IN FORCE DECLARES NO DIRECTION (CONTRACT K13): the chain's first link is the phase the
    # reading does not put in force, so the run the top hop reads is the OTHER pole's -- read exactly as
    # an unmeasured top is, and the sign swap (which seats by side) can never seat it.
    if getattr(ch, "premise_off", False):
        return ("unsettled", "unsettled")
    top = ch.hops[0]
    # A TOP HOP WHOSE POLE IS NOT IN FORCE AND CARRIES NO READING ON IT DECLARES NO DIRECTION (the
    # 09-23 fix round, W-7 -- the max turn's "cool-phase side" chain): the series' run is the OTHER
    # pole's, so reading it as this hop's move gave the chain a side it never had, and the sign swap
    # seats a chain by its SIDE, whatever it scored. It is read exactly as an unmeasured top is.
    if _pole_absent(top):
        return ("unsettled", "unsettled")
    mv = (1 if top.run_direction == "up" else (-1 if top.run_direction == "down" else 0))
    if not mv:
        mv = (top.move > 0) - (top.move < 0)
    if not mv:
        return ("unsettled", "unsettled")
    up = _SIGN_INT[ch.declared_sign] * mv > 0
    return ("higher" if up else "lower", "for" if up else "against")


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


def event_interval(event_date, precision: str = "") -> tuple:
    """THE CALENDAR INTERVAL A DATED EVENT COVERS, AT ITS OWN PRECISION -- ``(ISO start, ISO end)``,
    ``()`` when the date cannot be placed (CONTRACT C7).

    ``contracts.py`` declares the field pair: ``event_date`` plus ``event_date_precision`` in
    ``{day, month, quarter, year}``. The extractor NORMALISES a coarse date to its first day, so
    "during 2026" is stored as 2026-01-01 -- and a reader of the bare date sees a day nobody wrote
    (cotton FA-5: "[E48], dated January 2026" for a note that said "during 2026"). The interval is the
    fact the precision declares: a year is its whole year, a quarter its three months, a month its
    days, and a day (or an undeclared precision, read at face value as HEAD read it) is itself."""
    ed = str(event_date or "")[:10]
    placed = axis_date(ed)
    if not ed or placed is None:
        return ()
    y, m = int(placed[0:4]), int(placed[5:7])
    p = str(precision or "").strip().lower()
    if p == "year":
        return ("%04d-01-01" % y, "%04d-12-31" % y)
    if p == "quarter":
        q0 = 3 * ((m - 1) // 3) + 1
        return ("%04d-%02d-01" % (y, q0), _month_end_iso(y, q0 + 2))
    if p == "month":
        return ("%04d-%02d-01" % (y, m), _month_end_iso(y, m))
    day = ed if len(ed) == 10 else placed
    return (day, day)


def _month_end_iso(y: int, m: int) -> str:
    """The last calendar day of ``y-m`` as ISO -- pure calendar arithmetic, no clock."""
    import calendar
    return "%04d-%02d-%02d" % (y, m, calendar.monthrange(y, m)[1])


def event_when_words(interval, precision: str = "") -> str:
    """The event's date AT ITS PRECISION, in words: ``during 2026``, ``in the first quarter of 2026``,
    ``in January 2026``, ``on 2025-03-10`` (a day keeps the ISO spelling every HEAD receipt sentence
    already carries). ``""`` when there is no interval. These are the TRACE's words; the page's date
    words are the render's (CONTRACT C7)."""
    iv = tuple(interval or ())
    if len(iv) != 2 or not iv[0]:
        return ""
    p = str(precision or "").strip().lower()
    if p in ("year", "quarter", "month"):
        # THE PAGE'S OWN CALENDAR WORDS (render.event_when_words: ORDINAL_WORDS / month_words) -- one
        # producer of date words for trace and page alike; the day stays ISO in the trace (the receipt
        # sentences HEAD's trace already carries).
        from leviathan.graphrag.state import render as _rnd
        return _rnd.event_when_words(iv, p)
    return "on %s" % iv[0]


#: THE STORE'S DOCUMENT-DATE KINDS AT THEIR CALENDAR PRECISION (FIXER PASS, REVIEW_WT MAJOR-2). The kinds are
#: `evidence.doc_date_detail`'s own (key / key_month / doc_field / year_floor / epoch_floor, written into the
#: prop meta as `date_kind` and projected by `pgstore._project`); each declares what the document DATE is:
#: a parsed day, the first day of a release MONTH, a year FLOORED to 1 January. An epoch floor dates nothing
#: and has no entry (the document cannot be placed -- fail closed). A record carrying no kind is read at face
#: value, as a day -- HEAD's reading of every date.
DOCUMENT_DATE_PRECISION: dict = {"key": "day", "doc_field": "day", "key_month": "month", "year_floor": "year"}


def document_interval(c: dict) -> tuple:
    """THE DOCUMENT'S OWN DATE AS THE INTERVAL ITS KIND DECLARES -- ``(ISO start, ISO end)`` or ``()``.

    596 documents in the store are dated to a MONTH floor (usda_wap ``release_month=``, wb_cmo_outlook
    ``release=``) and 62 to a YEAR floor: their ``date`` is the first day of a period, never the day they
    were written, and a rule that reads it as a day files a real action reported inside that month as a
    forecast about the future (REVIEW_WT MAJOR-2, probes/p2_floored_doc: a CMO outlook keyed April 2022
    reporting a ban "from 28 April 2022")."""
    if not isinstance(c, dict):
        return ()
    doc = str((c.get("document_date") if "document_date" in c else c.get("date")) or "")[:10]
    if not doc:
        return ()
    kind = c.get("document_kind") if "document_kind" in c else c.get("date_kind")
    if kind in (None, ""):
        return (doc, doc)
    prec = DOCUMENT_DATE_PRECISION.get(str(kind))
    if not prec:
        return ()
    return event_interval(doc, prec)


def realised(c: dict) -> bool:
    """**DID THE DOCUMENT REPORT SOMETHING THAT HAS HAPPENED?** (CONTRACT K6, the 09-24 re-smoke's item 4;
    OWNER DECISION O-6 (a), which revises round 1's W-4.)

    True exactly when the event's WHOLE interval -- :func:`event_interval` at its own precision -- ends
    on or before the document's own date. A same-day day-precision action is realised (the day ends
    on the document's date); a month-precision event reported inside its own month is not yet whole
    (a straddle -- a dated report, :func:`hop_event`); an event dated after its document is a
    scheduled or conditional statement and is GUIDANCE until a later document reports it done.

    **IT FAILS CLOSED ON EVERY MISSING FACT, BECAUSE THE COMPARISON IS THE WHOLE RULE.** An empty
    precision has no interval to compare (the pg projection dropped it on 393 of 393 served hops on the
    09-24 traces -- CONTRACT K25 restores it, and this is the belt), and a document with no date of its
    own cannot say whether its event had happened when it was written; neither is ever an action. The
    rule reads DATES AND THEIR DECLARED PRECISION ONLY -- never a word of the proposition's text (the
    hedge-word reading, "if" / "could" / "expected", is the lexical fix the brief rejects).

    ``c`` is a :func:`hop_event` candidate (``event_date``, ``precision``, ``document_date``) or a raw
    evidence record (``event_date``, ``event_date_precision``, ``date``) -- the same three facts under
    the two spellings the estate carries them in.

    **THE DOCUMENT DATE IS AN INTERVAL TOO** (FIXER PASS, REVIEW_WT MAJOR-2): a document dated to a month
    or a year FLOOR (``date_kind``, :func:`document_interval`) was written somewhere inside that period, so
    its event is realised only when it ended on or before the period's first day -- the one day the
    document is certainly not earlier than. A document with no declared kind is a day (HEAD's reading)."""
    if not isinstance(c, dict):
        return False
    ed = str(c.get("event_date") or "")[:10]
    prec = str((c.get("precision") if "precision" in c else c.get("event_date_precision")) or "").strip()
    div = document_interval(c)
    if not ed or not prec or len(div) != 2:
        return False
    iv = event_interval(ed, prec)
    return len(iv) == 2 and bool(iv[1]) and iv[1] <= div[0]


def is_guidance(c: dict) -> bool:
    """A statement ABOUT THE FUTURE of its own document: the event's whole interval opens after the
    document's own interval closes (O-6's scheduled or conditional statement). An event that overlaps the
    document's own period -- a month-floored release reporting a ban from the 28th of that month -- is a
    REPORT, never guidance (FIXER PASS, REVIEW_WT MAJOR-2). Fails closed (False) on a missing fact."""
    if not isinstance(c, dict):
        return False
    ed = str(c.get("event_date") or "")[:10]
    prec = str((c.get("precision") if "precision" in c else c.get("event_date_precision")) or "").strip()
    div = document_interval(c)
    if not ed or not prec or len(div) != 2:
        return False
    iv = event_interval(ed, prec)
    return len(iv) == 2 and bool(iv[0]) and iv[0] > div[1]


def hop_event(receipts, *, asof: str, band: Optional[LagBand] = None, node_type: str = "",
              stamped: Optional[dict] = None) -> dict:
    """WHAT THE DATED DOCUMENT ON ONE HOP IS -- ``{kind, interval, event_date, precision, receipt,
    document_date}`` with ``kind`` one of :data:`EVENT_KINDS` (CONTRACT C7, the 09-23 event ledger;
    CONTRACT K6, the 09-24 re-smoke's realised-only rule).

    CHAIN-SCOPED BY CONSTRUCTION: it is called by :func:`chain_hop` and by nothing that runs on a
    chain-off turn, and it WRITES NOTHING -- ``row.event_open`` / ``row.event_date`` keep HEAD's
    reading because the loud set's re-take reads them (W-6).

    THE CANDIDATES are the documents with an ``event_date`` on or before the as-of (the point-in-time
    rule :func:`event_receipt_for` already applies -- a later event is a watch candidate, never a
    receipt). Each is classified against ITS OWN document date, by ONE ladder on every node type:

      1. **NO PRECISION, OR NO DOCUMENT DATE -> A DATED REPORT, NEVER AN ACTION** (K6, item 18's rule
         half). The event has no interval to compare, so it is ``report_in_reach`` / ``report_outside``
         on the recency bound read at the DOCUMENT's own date, and the returned ``interval`` is EMPTY:
         a reader of this dict is told the event's date is not an extent anyone declared, and prints
         the document date only. MEASURED on the 09-24 tariff turn: "2025-02-01" with no precision (the
         US order's date, a Saturday) printed as the day China announced its tariff.
      2. **REALISED** (:func:`realised`: the whole interval ends on or before the document date) -> an
         ACTION. HEAD's three on an ordinary node -- the declared window still running
         (``action_open``), shut within one band-length of the as-of (``action_closed``), shut before
         that (``action_aged``). On a node the graph TYPES as a regime (:data:`REGIME_NODE_TYPES`, owner
         decision 3) the NEWEST REALISED action is the regime -- superseded only by a later realised
         action on the same node -- and it reads ``regime_in_force``, or ``action_open`` while its own
         lag window still runs; a regime does not age. The WORDS name the action and the rule and never
         assert that any policy is in force today; the SCORE is direction-free.
      3. **A STRADDLE** -- the interval opens on or before the document's date and closes after it (a
         report written inside the period it describes, review WT F-1) -> ``report_in_reach`` /
         ``report_outside`` on the interval's END. Never an action, never worded as a forecast.
      4. **WHOLLY AFTER ITS DOCUMENT** -> ``guidance`` (``report_outside`` once its whole period closed
         more than one band-length before the as-of) -- ON EVERY NODE TYPE, which is OWNER DECISION O-6
         and REVISES round 1's W-4 ("a scheduled policy action, effective after its document date, is
         an ACTION"): the 2024-03-01 page promoted MPOC's "If the mandated biodiesel blend rate ... is
         raised to 15% from 10% beginning in April 2023" (documented 2023-03-28) into a policy regime
         in force, EVENT 12. A scheduled or conditional statement is guidance until a later document
         reports it done -- at which point THAT document's action is realised and is the regime.

    The chosen document is the best by DESIGN B.4's ladder (:data:`_EVENT_CHOICE_ORDER`) and, inside
    one kind, HEAD's own rule -- the newest event date, then the finer precision, then the earlier
    publication -- so a hop whose documents are all realised actions chooses exactly the document HEAD
    chose. On a regime node the newest REALISED action wins outright (DESIGN B.4's own "an enacted
    action first"); where the node carries no realised action the same ladder reads what it does carry.

    ``stamped`` is the row's own step-5 reading of HEAD's winner (``event_date``, ``event_open``,
    ``event_precision``). Where a candidate IS that winner its open/closed answer is READ from the
    stamp rather than recomputed: one reading of one document, whatever the caller built."""
    band = band if band is not None else parse_lag("")
    st = dict(stamped or {})
    st_date = str(st.get("event_date") or "")[:10]
    cands: list = []
    for r in (receipts or ()):
        if not r:
            continue
        get = (r.get if isinstance(r, dict) else (lambda k, _r=r: getattr(_r, k, None)))
        ed = str(get("event_date") or "")[:10]
        if not ed or (asof and ed > str(asof)[:10]):
            continue
        prec = str(get("event_date_precision") or "")
        if not prec and st_date and ed == st_date:
            prec = str(st.get("event_precision") or "")
        pub = str(get("date") or "")[:10]
        cands.append({"event_date": ed, "precision": prec, "document_date": pub,
                      "document_kind": get("date_kind"), "receipt": r,
                      "key": (ed, EVENT_PRECISION_RANK.get(prec, 3), pub)})
    if not cands:
        return {"kind": "none", "interval": (), "event_date": None, "precision": "",
                "receipt": None, "document_date": ""}

    def _newest(xs):
        # `event_receipt_for`'s own comparison, verbatim: max event date, then the FINER precision,
        # then the EARLIER publication; the first of an exact tie keeps its seat.
        best = None
        for c in xs:
            k = c["key"]
            if best is None or k[0] > best["key"][0] or (k[0] == best["key"][0]
                                                         and k[1:3] < best["key"][1:3]):
                best = c
        return best

    def _open(c) -> bool:
        if st_date and c["event_date"] == st_date and st.get("event_open") is not None:
            return bool(st.get("event_open"))
        return event_is_open(c["event_date"], band, asof)

    def _placed(c) -> bool:
        # THE TWO FACTS THE RULE COMPARES: a declared precision (an interval) and a document date whose own
        # kind places it (an epoch-floored document dates nothing -- REVIEW_WT MAJOR-2).
        return bool(str(c["precision"] or "").strip()) and len(document_interval(c)) == 2

    def _report_kind(c) -> str:
        # THE REPORT TIER, on the recency bound: a placed straddle on its interval's END (HEAD's WT F-1
        # reading); an unplaced candidate on its DOCUMENT's own date -- the one date it reliably carries.
        if _placed(c):
            iv = event_interval(c["event_date"], c["precision"])
            when = iv[1] if len(iv) == 2 else c["event_date"]
        else:
            when = c["document_date"] or c["event_date"]
        return "report_in_reach" if _date_in_reach(when, band, asof) else "report_outside"

    def _classify(c) -> str:
        """ONE candidate's kind on an ORDINARY node (the regime node reads the same ladder below)."""
        if not _placed(c):
            return _report_kind(c)
        iv = event_interval(c["event_date"], c["precision"])
        if realised(c):
            if _open(c):
                return "action_open"
            return "action_closed" if _date_in_reach(c["event_date"], band, asof) else "action_aged"
        if not is_guidance(c):
            # a straddle -- the event overlaps its OWN document's period (a day, or the month / year a
            # floored document date declares): a report inside its own period, never a forecast
            return _report_kind(c)
        # WHOLLY AFTER ITS DOCUMENT: a scheduled or conditional statement (O-6) -- guidance, on the
        # recency bound of the interval it is about; a spent one is a report outside the window.
        return "guidance" if _date_in_reach(iv[1] if len(iv) == 2 else c["event_date"], band,
                                            asof) else "report_outside"

    if str(node_type or "") in REGIME_NODE_TYPES:
        # THE REGIME IS THE NEWEST REALISED ACTION (K6). A statement about a period its own document sits
        # inside (review WT M-1 (b)), a scheduled or conditional statement (O-6) and an undated one are
        # never a dated action and can never supersede one; only where the node carries no realised
        # action at all is the ladder read over what it does carry.
        acts = [c for c in cands if _placed(c) and realised(c)]
        # FIXER PASS (REVIEW_WT MAJOR-1): THE REGIME CLAIM STANDS ONLY WHERE NOTHING LATER ON THE NODE COULD
        # HAVE REVERSED IT. The newest realised action is asserted as "the newest dated policy action on
        # this link that this turn retrieved" -- which is false when the draw holds a LATER dated document
        # on the same node that the ladder could not place as an action: an unplaced one (no stored
        # precision) or a report written inside its own period (the tariff page's own reversal: the 2020
        # exclusion stored at month precision, reported in March 2020, lost the regime to the 2018 duty).
        # Such a document is weighed, never skipped: the node then reads the REPORT tier on the newest of
        # them, and no older action is called the regime. Guidance (a scheduled or conditional statement,
        # O-6) is not a later event and never supersedes.
        later = []
        if acts:
            _c0 = _newest(acts)
            _iv0 = event_interval(_c0["event_date"], _c0["precision"])
            _end0 = _iv0[1] if len(_iv0) == 2 else _c0["event_date"]
            later = [x for x in cands if x is not _c0 and not realised(x) and not is_guidance(x)
                     and str(x["event_date"]) > str(_end0)]
        if acts and later:
            c = _newest(later)
            kind = _report_kind(c)
        elif acts:
            c = _newest(acts)
            kind = "action_open" if _open(c) else "regime_in_force"
        else:
            by: dict = {}
            for c in cands:
                by.setdefault(_classify(c), []).append(c)
            kind = next(k for k in _EVENT_CHOICE_ORDER if k in by)
            c = _newest(by[kind])
    else:
        by = {}
        for c in cands:
            by.setdefault(_classify(c), []).append(c)
        kind = next(k for k in _EVENT_CHOICE_ORDER if k in by)
        c = _newest(by[kind])
    rc = c["receipt"]
    receipt = (dict(rc) if isinstance(rc, dict) else
               {"date": str(getattr(rc, "date", "") or ""),
                "source": str(getattr(rc, "source", "") or ""),
                "text": str(getattr(rc, "text", "") or ""),
                "tier": getattr(rc, "tier", 3), "event_date": c["event_date"],
                "event_date_precision": c["precision"]})
    # AN UNPLACED DATE HAS NO INTERVAL (rule 1): the returned extent is empty, so no reader can print the
    # stored first-of-period as a day the document never wrote.
    return {"kind": kind,
            "interval": (event_interval(c["event_date"], c["precision"]) if _placed(c) else ()),
            "event_date": c["event_date"], "precision": c["precision"], "receipt": receipt,
            "document_date": c["document_date"]}


def hop_event_kind(hp, asof: str = "") -> str:
    """THE :data:`EVENT_KINDS` WORD FOR A HOP, whoever built it. A walked hop carries the classifier's
    word (:func:`chain_hop`); a hop built by hand carries ``""`` and is read by HEAD's own rule over
    its ``event_open`` / ``event_date`` / ``event_receipt`` -- the three words HEAD had -- so a pin's
    stand-in and a served hop can never be read two ways."""
    k = str(getattr(hp, "event_kind", "") or "")
    if k in EVENT_KINDS:
        return k
    if getattr(hp, "event_receipt", None) and getattr(hp, "event_date", None):
        if getattr(hp, "event_open", False):
            return "action_open"
        return "action_closed" if _receipt_in_reach(hp, asof) else "action_aged"
    return "none"


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
    closes = _add_months(event_date, int(band.max_q) * QUARTER_MONTHS)
    return bool(closes) and closes >= str(asof)[:10]


def _add_months(iso: str, months: int) -> Optional[str]:
    """ISO date + N months, clamped to the month end. Pure calendar arithmetic, no clock.

    THE LABEL IS PLACED FIRST (2026-09-10, the S4 mirror run's other half): ``feeders._period_dates``
    legitimately writes a bare ``YYYY`` for a marketing-year card with no month (ten annual tables on
    the mirror), and slicing ``iso[5:7]`` on it is ``int("")`` -- the ``ValueError`` that took 35 boards
    at quick through render's SB-J anchor. ``analogs.axis_date`` names that form first-class (a bare
    year is its 31 December; a ``YYYY-MM`` its month end) and returns ``None`` for a label it cannot
    place, which every caller here turns into a DECLINE rather than a raise."""
    placed = axis_date(iso)
    if placed is None:
        return None
    y, m, d = int(placed[0:4]), int(placed[5:7]), int(placed[8:10] or 1)
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
    if opens is None:                                   # an anchor the calendar cannot place
        return {"opens": None, "closes": None, "open_ended": False, "declined": "lag_unparsed"}
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
    if at is None:
        return None
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
         analog_reads: bool = True, state_chain: bool = False, spread_fn=None) -> B.Board:
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
    # THE QUESTION'S REACH (CONTRACT K9), re-derived from the anchors' own distance-0 set -- the markets
    # the question named or the planner planned, which `resolve_anchors` stamped as `Anchor.distance` --
    # and ONLY where it stamped one: a turn the subject resolver did not reach carries no distance on
    # any anchor and this board's reach stays empty, byte for byte HEAD's board (B4). Zero reads, and
    # computed BEFORE the anchor ceiling, so a planned market the ceiling later cuts is still one of the
    # question's own markets.
    if any(getattr(a, "distance", None) is not None for a in bd.anchors):
        bd.question_reach = question_reach(
            graph, named=tuple(a.contract for a in bd.anchors if getattr(a, "distance", None) == 0))

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
        # `state_chain` IS ON THE ONE-CALL SHAPE TOO, and it is APPENDED LAST with the same default.
        # The serving seam drives the two stages separately (:func:`stage2`); the HARNESS and the BOARD
        # CENSUS drive them in one call, and without the kwarg here the estate's own block census could
        # not arm the leg at all -- which is how it came to be chain-blind in both directions (the
        # round-2 census's blocker 5). Absent, not one byte of this function moves.
        _stage2(bd, graph, kn, key_fn=key_fn, state_fn=state_fn, receipts=receipts, width=width,
                legb_cells=legb_cells, legb_on=legb_on, complexes=complexes, chains=chains,
                turn_kind=turn_kind, analog_reads=analog_reads, state_chain=state_chain,
                spread_fn=spread_fn)
    return bd


def stage2(bd: B.Board, graph, *, state_fn=None, key_fn=None, receipts=None, width: int = 2,
           legb_on: bool = False, complexes=(), chains=(), analog_reads: bool = True,
           state_chain: bool = False, spread_fn=None, extra_periods=()) -> B.Board:
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
    would price a wave against a rank that does not exist.

    ``state_chain`` IS THE S8 CHAIN MOVEMENT'S OWN SWITCH AND IT IS A KWARG, NEVER AN ENVIRONMENT
    READ. `state/` reads no environment and that law does not bend here: `answer._state_chain_on()`
    reads `GRAPHRAG_STATE_CHAIN` ONCE at the answer seam and threads the boolean, exactly as
    `watch_nonobvious` does. Default False -> no chain is built, `Board.chains` stays empty,
    `Board.trace()` omits the key, the `path` leg keeps HEAD's stamp and the render caps keep the
    tier's own -- i.e. every rendered byte of a board-on / chain-off turn is the 2026-09-16 smoke's.

    ``spread_fn`` IS THE RV SEAT, DECLARED AND UNWIRED -- see :func:`chain_rows`.

    ``extra_periods`` (FIXER PASS, REVIEW_VC M2 / RA M7 -- CONTRACT K23's seat half): the numbers seat's
    SERVED calls, which exist only by stage 2. They join the cross-card store-period pass
    (:func:`restamp_store_period`) before anything in stage 2 reads a rank. Empty (every caller that
    threads none, and every board-off turn) -> HEAD's stage 2 exactly."""
    if bd.knobs is None or not bd.anchors or not bd.stage_done.get(1):
        return bd
    if extra_periods:
        restamp_store_period(bd, extra_periods)
    _stage2(bd, graph, bd.knobs, key_fn=key_fn, state_fn=state_fn, receipts=receipts, width=width,
            legb_cells=B.legb_cells_of(bd.mode), legb_on=legb_on, complexes=complexes, chains=chains,
            turn_kind=bd.turn_kind, analog_reads=analog_reads, state_chain=state_chain,
            spread_fn=spread_fn)
    return bd


def _stage1(bd, graph, kn, *, key_fn, state_fn, turn_kind, width, positioning_ids,
            admit_order=None) -> None:
    """STEPS 0-4 of sec 3.3: rows (0 reads), price wave 1 (0 reads), ONE wave, state, rank, loud set.

    ``admit_order`` is COLD START's priced positions (``{label: position}``); when present it replaces
    the `anchor board first` term for a key the pricer admitted, so the wave-1 cut IS the priced set.
    On every other turn it is ``None`` and the term is the anchor ordinal sec 3.8 declares."""
    t0 = time.perf_counter()
    key_fn = key_fn or _default_key_fn
    # THE SUBJECT ROWS, PER BOARD, FROM THE ANCHORS THEMSELVES (SUBJECT RESOLVER D6). This read
    # `bd.subject_driver` and matched ONE id, which is the second reader of the `focus_driver`
    # predicate the resolver's landing missed: on the FE path 6 of 6 `cot_mm_positioning` rows were
    # marked and on the resolved-subject path 0 were, leaving a row `context_only` on the very turn
    # whose subject it is. `subject_ids_on` answers for BOTH sources and for a GROUP -- five
    # positioning ids are one subject, and the exception is owed to whichever of them a board carries.
    #
    # THE D6 AMENDMENT'S ROW-ORDER HALF IS PHASE B'S, AND THIS IS ITS EXACT SEAM (declared 2026-09-10,
    # NOT built here). The amendment has two halves: "NAMED markets each with the subject's row LEADING
    # INSIDE IT". The anchor-ORDER half is built and pinned (`board.ANCHOR_ORDER`, `anchor_order_key`,
    # `resolve_anchors`'s sort, and the deck's "corn leads" test). The ROW-ORDER half needs three
    # changes and every one of them moves a MEASURED quantity, which is why it is not taken in a fix
    # round that can only re-read layer 1:
    #   (i)   THIS LINE. `Anchor.subject` is the POSITIONING exception flag (Amendment 1), not "this
    #         anchor carries the subject", so today only positioning rows are marked at all. Phase B
    #         reads `a.source in B.DRIVER_ANCHOR_SOURCES` and takes the ids from `bd.subject_ids_on`,
    #         which already answers for both driver sources and for a group.
    #   (ii)  `rank_key_for` / `rank_rows` -- the ONE producer of within-board row order, stored by
    #         `Board.set_order` and read by `render.render_board`'s `order` dict and by nothing else. A
    #         subject-leading term is a new FIRST element of that tuple (`0 if row.subject else 1`),
    #         applied per board so it cannot reorder boards against `ANCHOR_ORDER`.
    #   (iii) `loud_set`, which re-ranks each board's rows with the same key and cuts at `loud_k`. A
    #         row promoted to the front of a board therefore DISPLACES the loudest row that sat in the
    #         last surviving seat -- a rendered-content change on every subject turn, at every tier,
    #         which needs its own measurement and is exactly what layer 1 cannot grade.
    subject_slugs = {a.contract for a in bd.anchors if a.subject}
    subject_ids = {c: set(bd.subject_ids_on(c)) for c in subject_slugs}

    # 0  rows = EVERY node of EVERY anchor DAG -- never filtered, whatever tier it lands in.
    priced, plans = [], {}
    for order, a in enumerate(bd.anchors):
        contract = (getattr(graph, "contracts", {}) or {}).get(a.contract)
        for d in (getattr(contract, "drivers", ()) or ()):
            row = _node_row(graph, a.contract, d)
            # POSITIONING AS SUBJECT (Amendment 1): `context_only` yields when the query names the
            # driver being explained. It is set on the ROW, so every consumer of the rule reads one
            # field rather than re-deriving the exception.
            if d.id in subject_ids.get(a.contract, ()):
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

    # THE PERIOD GAP THE RANK READS (C11, W-12; the 09-23 verifier's F1): a fact about the STORE, stamped
    # over the states this wave SERVED -- a row is behind only where a sibling series of its own slug on
    # its own card came back holding a NEWER period as known at the as-of. Zero reads; it must land
    # before the rank, because `coverage_band` demotes on it.
    from leviathan.graphrag.state import feeders as _F
    _F.stamp_period_gaps([row.state for row in bd.rows if row.state is not None], bd.asof)

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


def restamp_store_period(bd, extra_periods) -> int:
    """THE K23 SEAT HALF (FIXER PASS, REVIEW_VC M2 / RA M7 / the integrator's F-3). Stage 1 stamps the
    cross-card store period over the BOARD's own served states (``feeders.stamp_period_gaps`` ->
    ``stamp_period_behind``) and ranks on it; the numbers SEAT's served calls -- the 2024 page's WASDE
    2023/24 sheet, the one newer period the store held beside PSD's MY2020 rows -- arrive only at stage 2.
    So they are joined here, at zero reads, and every row whose ``period_behind`` stamp CHANGED has its rank
    tuple re-taken under the board's own rule (``coverage_band`` demotes on the stamp, one band, never
    stacked with ``period_gap``). Stage 2's loud-set re-take and the final ``board_order`` then read the
    corrected ranks, so a row the store holds a newer year of is labelled AND ordered as behind. Returns
    the number of rows whose stamp moved."""
    from leviathan.graphrag.state import feeders as _F
    rows = [r for r in (getattr(bd, "rows", None) or ()) if getattr(r, "state", None) is not None]
    before = {id(r): dict(getattr(r.state, "period_behind", None) or {}) for r in rows}
    try:
        _F.stamp_period_behind([r.state for r in rows], bd.asof, extra_periods=tuple(extra_periods or ()))
    except Exception:  # noqa: BLE001 -- a stamp pass that cannot run leaves stage 1's stamps standing
        return 0
    moved = [r for r in rows if dict(getattr(r.state, "period_behind", None) or {}) != before[id(r)]]
    if moved:
        key = rank_key_for(bd.rank_rule)
        for r in moved:
            r.rank = key(r)
        board_order(bd)
    if moved:
        try:
            bd.notes.append({"kind": "period_behind_seat", "moved": len(moved)})
        except Exception:  # noqa: BLE001 -- telemetry never costs the stamp
            pass
    return len(moved)


def _stage2(bd, graph, kn, *, key_fn, state_fn, receipts, width, legb_cells, legb_on, complexes,
            chains, turn_kind, analog_reads: bool = True, state_chain: bool = False,
            spread_fn=None) -> None:
    """STEPS 5-14 of sec 3.3: receipts, EVENT rows, the closure, the edges, the free fan, wave 2's
    price, wave 2, convergence, complexes and chains. IT NEVER RE-RANKS STAGE 1."""
    t0 = time.perf_counter()
    key_fn = key_fn or _default_key_fn
    receipts = receipts or {}
    # THE SUBJECT'S STANDING IN THE QUESTION'S REACH (CONTRACT K9, O-5): stamped here because the seam
    # writes `Board.subject` between the two stages; EMPTY on every turn the resolver did not reach.
    bd.subject_reach = subject_standing(bd, graph)

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
    # "THE SAME READING" IS ONE SERIES (CONTRACT K26), stamped on every far row the index named.
    fan_identity(bd, graph, key_fn=key_fn, turn_kind=turn_kind)

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
        # WHICH TAIL EACH READ CONDITION SITS IN (the 09-25 fix round, W-2 / N4): the pattern counts a
        # condition only in the tail its card declares for it. Rides GRAPHRAG_STATE_BOARD (this stage runs
        # only for the board); zero reads -- every figure is the row's own served standing.
        sides = {r.driver_id: s for r in loud_by_board.get(slug, ())
                 if r.driver_id in read_ids for s in (row_side(r),) if s is not None}
        rows = convergence_rows(graph, slug, ids, loud_k=int(kn.loud_k), band_ids=banded,
                                measured_ids=read_ids, sides=sides)
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
    # THE NODE AXIS IS PASSED BESIDE THE BOARD AXIS because the estate's ten curated chains are keyed
    # on DRIVER ids and its two transmission chains on MARKETS -- two shapes, two joins, declared per
    # row by `chain_row_shape` rather than guessed for the file (see its note: the board-slug reading
    # raises on the first curated row and has never been exercised because `chains` is always empty).
    # IT IS KEYED ON `(contract, driver_id)` (E11): `NodeRow.key` is that pair and `area` is a driver
    # of corn AND of wheat, so a flat id set would let one board's rows order another board's chain.
    on_nodes = {r.key for r in bd.rows}
    loud_nodes = {r.key for r in loud}
    bd.notes.append({"kind": "complexes", "rows": tuple(
        (tuple(c["pair"]), c["rendered"]) for c in complex_pairs(complexes, on_board))})
    bd.notes.append({"kind": "chains", "rows": tuple(
        (c["name"], c["rendered"], c["loud_hops"])
        for c in chain_paths(chains, on_board, loud_boards=loud_boards,
                             on_nodes=on_nodes, loud_nodes=loud_nodes))})

    # 13b THE COMPOSED CHAIN (S8 lane W, sec 3.5b). DARK: nothing below this line runs, stamps or
    #     moves a byte unless the caller threaded `state_chain=True`, so a board-on / chain-off turn
    #     is byte-identical to the 2026-09-16 smoke and a flag-off turn is byte-identical to HEAD.
    if state_chain:
        # STEP 5's OWN RECEIPT MAP rides into the chain leg (the 09-23 fix round) so each hop's dated
        # document is classified over the list step 5 read -- and ONLY here, on the chain path.
        got = chain_rows(bd, graph, knobs=kn, chains=chains, spread_fn=spread_fn, receipts=receipts)
        bd.chains = got["pool"]
        bd.chain_counts = dict(got["counts"])
        bd.chain_counts["disagreement"] = got["disagreement"]
        bd.trace_rows = True
        # THE LEG KEEPS ITS NAME. `path` is the leg that cut topology lines and is now the leg that
        # cuts chains; re-stamping it here rather than minting a `chain` leg is what keeps every
        # banked decline histogram, every EMF dimension and every census row meaning what it meant
        # (`board.CHAIN_REASONS`' own note). The path leg's own stamp two steps up is OVERWRITTEN and
        # not appended to, because a leg carries ONE outcome and two would be a leg that both fired
        # and declined.
        if any(c.rendered for c in bd.chains):
            bd.stamp("path", "fired")
        elif bd.chains:
            # A POOL WITH NOTHING RENDERED IS A CAP OF ZERO, and that is the only way it can happen
            # now the print line no longer cuts (owner ruling 6): the top K always render. The word
            # names the cause rather than a line the selection no longer reads.
            bd.stamp("path", "declined", reason="render_cap")
        elif got["counts"].get("cross_unpriced"):
            bd.stamp("path", "declined", reason="cross_unpriced")
        else:
            bd.stamp("path", "not_reached")
        # THE A.8 ENUMERATION CUTS LAND IN THE SAME PLACE THE CHAIN ROWS DO (threat E1: "the A.8 cuts
        # land in the SAME commit as the chain rows, and the census is a build gate"). They ride the
        # KNOBS rather than the tier table so the control cell cannot move with the treatment -- see
        # `board.CHAIN_RENDER_CAPS`. It happens HERE, at the foot of stage 2, because every read this
        # board will make has been made: the four knobs it moves are render enumerations and reach no
        # budget, no loud cut and no analog column.
        bd.knobs = B.with_chain_caps(bd.knobs, bd.mode)

    # 14 the windows the board hands `quantify` (sec 3.9 item 2) and the recency ledger's own facts.
    for r in bd.rows:
        st = r.state
        if st is None or not r.legs.get("loud"):
            continue
        near = ((st.run or {}).get("since_date") if st.run and not st.run.get("declined") else None) \
            or st.level_date
        # ``reading`` IS A THIRD ANCHOR AND ``near`` IS NOT TOUCHED (S7b, critique R6). The two answer
        # DIFFERENT questions and the design declares both. SB-J asks "when does the effect of this
        # STATE land", and :func:`projection_window`'s own docstring fixes its anchor at the run's
        # start -- "a lag runs from the state to the effect" (Judge 2) -- so ``near`` stays the run
        # start and every SB-J line on every board-on turn is byte-identical.
        # A WATCH ROW ASKS "from the reading I am looking at, when does the window close", and counting
        # that from a run start that began in 1997 produces a window that closed in 1998 for a 2026
        # reading: MEASURED at 10 of the 60 rows of the 09-11 non-obvious prototype (palm "China food
        # demand" rendered 1997-12..1998-06). So the reading's OWN date is banked beside the run start,
        # and the watch producer reads it under its own flag.
        # IT IS ADDITIVE AND NEVER A REPLACEMENT: a consumer that wants the run start reads ``near``,
        # a consumer that wants the observation reads ``reading``, and neither has to know which one
        # the other took. ``state_date`` already carried the same value and is left alone because it is
        # the recency ledger's field, not the projection's -- two readers, two names, no aliasing.
        bd.windows[r.key] = {"near": near, "state_date": st.level_date, "reading": st.level_date,
                             "knowledge_date": st.knowledge_date, "analog_dates": ()}
    # sec 3.9 item 1 again -- and it is NOT a re-rank of stage 1. The numeric head reads the tuple stage
    # 1 stamped (`stored_rank`); only the TEXT-ONLY tail moves, and sec 3.2 says in so many words that
    # its order "is computed in STAGE 2", because `newest receipt date` does not exist before `ground()`.
    board_order(bd)
    # A LEXICAL `max` OVER MIXED DATE SPELLINGS PICKS THE WRONG DATE (lane A's measured defect, handed
    # to this line in round 2's HANDOFF and taken here): the ESR rows stamp `20260904` and the PSD rows
    # `2026-09-14`, and `"20260904" > "2026-09-14"` because `-` (0x2D) sorts below `0` (0x30) -- so a
    # ten-day-old stamp won a comparison it should have lost, and the served ledger sentence stated it.
    # NORMALISE BEFORE THE COMPARISON AND STORE THE NORMALISED VALUE: a print-side fix spells the WRONG
    # date correctly. `narration.iso_date` is lane A's ONE producer and returns an unparseable value as
    # given, so no date is invented and no second normaliser is written here.
    from leviathan.graphrag.state.narration import iso_date as _iso_date
    bd.recency["numbers"] = max((_iso_date(st.knowledge_date) or ""
                                 for st in bd.series.values()), default="")
    bd.recency["text"] = max((_iso_date((r.receipts or {}).get("newest_date")) or ""
                              for r in bd.rows), default="")
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
