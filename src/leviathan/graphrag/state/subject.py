"""THE SEMANTIC SUBJECT RESOLVER -- three deterministic tiers over the DRIVER vocabulary (D1-D6).

Design: ``docs/private/SUBJECT_RESOLVER_SITTING_2026-09-09.md``; recon (every figure below is measured
there): ``scratchpad/recon_resolver/BRIEF.md``.

WHAT THIS MODULE IS FOR. The estate's ONE lexical matcher (``answer.route_scored``) matches CONTRACTS:
its ``forms`` list is the contract slug, its de-underscored form, ``CausalContract.aliases`` and the
slug's own tokens. A DRIVER is in none of them, so until this module there was no path at all from a
typed phrase to a driver id -- ``focus_driver`` was minted only by an FE click or an event record.
MEASURED baseline over the recon's thirty synonym / misspelling / description phrases, using the
strongest driver resolution the shipped tree affords (``evidence.driver_slices_for`` inverted through
``driver_alias``): **30.0% any-hit, 23.3% hit@1**; descriptions 1/10 and misspellings 2/10. That is the
number this module exists to beat, and the owner's word that opened the sitting is the reason it must:
"lexical? are you serious?" -- a desk types spellings, synonyms and descriptions.

THE EMBEDDER PROPOSES, THE PLANNER DISPOSES (D2). Nothing here decides a subject. The three tiers
produce :class:`SubjectHints`, the orchestrator renders :func:`hints_line` into the planner's USER
message, and the planner returns ids from an enum which ``dispatch._validate`` re-verifies against the
live id set. This module never anchors, never routes and never writes a trace key.

WITH ONE FENCE, AND IT IS ON THE ENUM RATHER THAN ON THE PROMPT (phase D, 2026-09-10).
:data:`OWN_STRUCTURE_IDS` is the closed set of ids that ARE the anchor's own price structure -- its
curve, its cash-versus-board -- and so are a CONDITION and never a cause. They are absent from
:func:`live_ids`, from :func:`hints_line` and from :meth:`SubjectHints.ambiguous`, and present in
:func:`all_ids`, which is what the tiers match over. The measurement that made it an enum question
rather than a prompt one is in the phase-D addendum at the foot of this file.

IT IS ENV-FREE, AND THAT IS GRADED. ``config_check.check_state_seam`` clause (i) allows exactly ONE
environment name across ``state/*`` (``GRAPHRAG_STATE_CACHE``); ``check_subject_resolver`` clause (1)
greps THIS file for any read at all. The flag ``GRAPHRAG_SUBJECT_RESOLVER`` is read ONCE at the
``answer``/orchestrator seam and threaded, the way ``GRAPHRAG_STATE_BOARD`` and ``GRAPHRAG_COMOVE``
are. There is no ``import os`` in this file on purpose.

THE THREE TIERS (D3):

  T0 EXACT   the query contains a driver id or its reader form ('El_Nino' -> 'El Nino'), through
             ``harvest.build_matcher`` -- THE ONE SHIPPED MATCHER, accent- and case-folded,
             word-boundary. Never a second matcher: a private copy drifts from the router on the first
             alias edit, which is the string-identity class this estate has measured three times.
             Zero embeds, and the FAIL-OPEN floor when the embedder or the artifact is gone.

  T1 ALIAS   ``evidence.driver_slices_for`` (the shipped ``driver_slices.yaml`` terms matcher, with its
             ``co_terms`` conjunction) inverted through ``evidence.driver_alias`` and INTERSECTED with
             the live id set. The intersection is load-bearing: the alias map carries 424 entries of
             which 127 point at ids no DAG declares (accent folds and curation drift) -- MEASURED, and
             ``walk._driver_of`` swallows an unknown id, so an untrusted alias would anchor NOTHING
             with no word for why. Still zero embeds. Reaches 297 of 405 ids (73.3%).

  T2 SEMANTIC  ``q = evidence.embed([query])[0]`` -- the VERBATIM query, because that is the key
             ``planner._parallel_fill`` pre-warms once per turn in ``evidence._Q_CACHE``, so on a lane
             that walks the embed is a dict hit. Embedding a SUBJECT SPAN instead is a new
             cache key and costs a MEASURED +350-550 ms, which alone is 2-4x the whole 150 ms budget.
             ``s = V @ q`` over the unit-norm artifact (cosine == dot; MEASURED 1.65 ms at 4,000x1,024),
             per-id score = MAX over that id's rows -- never a mean, because one id carries a different
             blurb on every board it sits on (166 of 405 ids; ``El_Nino`` carries 35) and a mean would
             dilute the most-shared drivers to nothing. Candidates = ids at or above :data:`CAND_FLOOR`,
             top :data:`TOP_K`.

             AND IT IS CONDITIONAL (D10, 2026-09-10): :func:`resolve` runs T2 **only when the free
             tiers named in** :data:`T2_GATE_TIERS` **found nothing** -- T0 and T1 as shipped -- so an
             explicit driver name never pays an embed. MEASURED on the calibration deck: 44 of 104 rows
             (42.3%) are answered by the two free tiers and cost 5.76 ms p50 instead of 351 ms. THE
             GATE IS NOT FREE AND ITS PRICE IS BANKED RATHER THAN ARGUED -- 5 of 90 true rows on the
             calibration deck and 14 of 92 on the HELD-OUT one (94.4% -> 88.9% and 93.5% -> 78.3%
             all-tiers), every one a phrase where a free tier matched a driver the question mentions
             IN PASSING while the subject is a driver only T2 reaches. The full table, the mechanism
             and the recommendation live on :data:`T2_GATE_TIERS`.

T2 RUNS ONLY ON AN ``ok`` ARTIFACT, AND THE OTHER THREE WORDS ARE THE FAIL-OPEN FLOOR (D7). The
vocabulary is a BUILD artifact (``scripts/graphrag/build_subject_vocab.py``) and not a boot
computation, because bge-m3 embeds 1.4-2.7 texts/s on one CPU: the 4,000-row vocabulary is 20-48
MINUTES against an ECS ``health_check_grace`` of 300 s. So it is np.loaded ONCE PER PROCESS -- MEASURED
at 133 / 180 / 166 ms on a cold OS page cache for the 25.2 MB artifact that actually ships (~153 ms on
an independent 2026-09-10 draw; 57.5-63.2 ms, n=5, once the file is in the page cache), which is
one-time and outside every per-turn budget in this file -- its stamped ``graph_hash`` is compared to ``graph.causal_graph_version()`` on every load,
and a mismatch DECLINES the tier with the word ``stale`` while ``config_check`` REDS THE BUILD. T0 and
T1 still run on every one of ``missing`` / ``stale`` / ``unreadable``: a resolver failure must never
take a turn down (``state/seam.py``'s "a board must never break a turn" and ``dispatch``'s "routing
must never break an answer" are both precedents).

SUBJECT GROUPS (D4) are the answer to the estate's own near-duplicate ids -- four fertilizer ids, three
crude ids, three EUDR ids, five positioning ids, four ids for one FX pair. Under any margin rule those
tie by construction, so a CORRECT resolution would be reported as a decline on some of the most-asked
subjects. That is a curation gap surfacing as an engineering problem, and the estate already carries
the two keys that close it: :func:`groups` is measured and banked in ``tests/unit/test_subject_resolver.py``.
"""
from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------------------------------
# THE FROZEN CONSTANTS (D9) -- CALIBRATED on configs/graphrag/subject_deck_v1.yaml, never guessed
# ---------------------------------------------------------------------------------------------------
#: THE CANDIDATE FLOOR. A per-id max-cosine at or above this becomes a hint the planner may read.
#:
#: CALIBRATED 2026-09-09 on the 104-row deck against the real artifact (graph 99dc11409fe9, 4,000 rows,
#: bge-m3), NOT inherited: ``answer.route_semantic``'s own ``min_cos = 0.35`` is over a DIFFERENT
#: population (36 contract profiles, not 405 driver ids) and does not transfer.
#:
#: 0.52 IS THE KNEE, and it is a measured one. Every true class holds its maximum rate from 0.46 all
#: the way to 0.52 -- exact 10/10, alias 9/10, synonym 10/14, misspelling 13/14, description 14/14,
#: acronym 10/10, near_duplicate 10/10, multi 8/8 -- while the number of DECOY rows carrying any
#: candidate at all falls from 11 to 7. At 0.53 near_duplicate drops to 9/10 and at 0.545 description
#: drops to 13/14, so 0.52 is the last floor that costs nothing and the cheapest that buys anything.
CAND_FLOOR = 0.52

#: THE AMBIGUITY FLOOR (D5). At or above THIS, a candidate the planner declined to pick is CARRIED into
#: the answer as ``subject_ambiguous`` rather than dropped. It is >= :data:`CAND_FLOOR` by construction
#: (asserted below): a score too weak to hint with is far too weak to interrupt a reader over.
#:
#: THE TWO POPULATIONS OVERLAP, AND THE FLOOR IS TAKEN ON THE DECOY SIDE. Measured on the deck: the
#: worst DECOY scores **0.7360** (dc13, "compare wheat corn and soybeans over the last month" ->
#: ``soybean_corn_price_ratio``) while the weakest true DESCRIPTION scores **0.5427** and the weakest
#: true row of any class scores **0.4396**. No single number separates them -- the strongest decoy
#: outranks most of the deck's true rows. Risk 3 predicted exactly this: the vocabulary is 405 ids of
#: ag-market prose, so ANY ag question scores non-trivially against something.
#:
#: So the two floors do two different jobs. ``CAND_FLOOR`` fences a LIST THE PLANNER READS, and the
#: planner is that list's fence (D2: the embedder proposes, the planner disposes). ``AMBIG_FLOOR``
#: fences a row that INTERRUPTS A READER, and nothing else fences it -- so it sits ABOVE every decoy
#: the deck measured. 0.74 is the lowest sweep point with zero decoy carries and it clears dc13 by
#: 0.004, which is not a margin; 0.78 clears it by 0.044 and costs NOTHING measurable, because no
#: non-decoy row on the deck carries two candidates in different groups above 0.74 either.
#:
#: THE CONSEQUENCE IS STATED RATHER THAN HIDDEN: at this floor the ambiguity carry is a RARE-EVENT
#: instrument. It fires on no row of the calibration deck. That is the correct posture for a row that
#: stops and asks a reader a question, and it is the honest reading of the measurement -- a cosine
#: floor over this vocabulary cannot both admit genuine ambiguity and exclude decoys.
AMBIG_FLOOR = 0.78

if AMBIG_FLOOR < CAND_FLOOR:                                # a floor that admits what it must not carry
    raise AssertionError("AMBIG_FLOOR must be >= CAND_FLOOR")

#: How many semantic candidates ride the hint line. The deck's own bar is stated over the TOP-5, and
#: the sensitivity is MEASURED rather than assumed: at ``CAND_FLOOR`` the only class that moves with k
#: is synonym (9/14 at k=3, 10/14 at k=5, 11/14 at k=8, 12/14 at k=10) and the number of DECOY rows
#: carrying a candidate does not move at all (7 at every k). Widening k is therefore a free-looking
#: knob that is NOT free: every extra candidate is another id the planner may take, and layer 2 -- the
#: billed measurement of what the planner does with the list -- has not run. k stays at the deck's own
#: bar until that measurement exists; the widening is docketed, not taken.
TOP_K = 5

#: WHICH FREE TIERS' OUTPUT SUPPRESSES T2 (D10, owner's word 2026-09-10: "an explicit driver name
#: never pays an embed"). ``()`` runs the semantic tier on every turn; ``("exact",)`` skips it when T0
#: matched; ``("exact", "alias")`` -- what ships -- skips it when either free tier named an id.
#:
#: IT IS A LATENCY KNOB WITH AN ACCURACY PRICE, AND BOTH SIDES ARE MEASURED ON BOTH DECKS. The saving
#: is real: the resolver runs BEFORE ``plan_turn``, so its embed is COLD (p50 351 ms) and a skip costs
#: 5.76 ms instead. The price is real too, and it is not small -- ALL-TIERS hit rate, then the share of
#: turns that pay an embed:
#:
#:     rule                    calibration (n=90 true)        held-out (n=92 true)      embeds paid
#:     ()        T2 always     85/90  94.4%                   86/92  93.5%              100% / 100%
#:     ("exact",)              83/90  92.2%  (-2 rows)        79/92  85.9%  (-7 rows)   81.7% / 90.9%
#:     ("exact","alias")       80/90  88.9%  (-5 rows)        72/92  78.3%  (-14 rows)  57.7% / 62.7%
#:
#: ONE MECHANISM PRODUCES EVERY LOST ROW: the free tiers match a driver the phrase mentions IN PASSING
#: -- a condition, a place, a consequence -- while the subject is a driver only T2 reaches, and a
#: non-empty wrong answer then suppresses the tier that would have been right ("pod fill" suppressing
#: `heat_stress`, "farmer selling" suppressing `BRL_FX` at 0.802). The decoy FATAL bar is clean under
#: every rule (zero carries at :data:`AMBIG_FLOOR`), so this is a hint-quality trade and never a safety
#: one.
#:
#: THE RECOMMENDATION ON THESE NUMBERS, STATED WHERE THE VALUE LIVES: the LANE knob does this job for
#: free. ``resolve(allow_embed=False)`` costs nothing in accuracy and saves the whole 351 ms on a lane
#: that will never walk, and on a lane that DOES walk the embed is the same ``_Q_CACHE`` key the walk
#: needs, so paying it early costs the turn ~0 (MEASURED: the walk's own embed afterwards is 0.007 ms).
#: This tuple therefore buys 37% of embeds on the turns where the cost was already ~0, for 15 points of
#: held-out hint accuracy. FLIPPED TO ``()`` BY THE ORCHESTRATOR 2026-09-10 ON THAT TABLE: T2 always runs
#: (93.5% held-out all-tiers hit against 78.3% under the gate); the lane knob ``allow_embed=False`` is the
#: only saving taken, on a lane decided BEFORE the planner. The gated behaviour stays banked in the deck
#: and this literal stays the one place to restore it.
T2_GATE_TIERS: tuple = ()

#: THE ALIAS HINT CEILING. One ``driver_slices`` slice can carry TEN ids (``freight``, ``tariff`` --
#: measured), and every one of them is the SAME subject group, so listing all ten spends the hint line
#: on a set the planner collapses back to one pick anyway. The tuple is bounded here rather than at the
#: render so the count the trace reports is the count the planner saw.
HINT_ALIAS_CAP = 8

#: THE ANCHOR'S OWN PRICE STRUCTURE -- A CLOSED SET, AND NEVER A SUBJECT (phase D, 2026-09-10).
#:
#: A SUBJECT IS A CAUSE. These two ids are not causes of the board they sit on: they ARE that board --
#: the same market's own curve (front against deferred) and the same market's cash against its own
#: futures. MEASURED on the shipped graph: ``calendar_spread`` is type ``instrument`` on NINE boards
#: with ``silver_ref`` ``spread`` / ``kc_calendar_spread`` / ``srw_calendar_spread``, and ``basis`` is
#: type ``instrument`` on FOUR with ``basis_z``. Naming either as THE SUBJECT asks the walk to explain
#: a market with itself, which is the self-reference ``cascade_map`` already refuses one layer down.
#: This is that same law, stated where the subject is chosen rather than where the cascade is drawn.
#:
#: THE OTHER 23 INSTRUMENT-TYPE IDS STAY, AND THE DISTINCTION IS THE WHOLE POINT.
#: ``soybean_crush_margin``, ``wheat_corn_spread``, ``soyoil_palm_premium``, ``oil_share``, the two
#: parity floors -- every one of them is a CROSS-market instrument the graph declares as a cause of a
#: DIFFERENT board, with a sign and a lag. "The soy-palm premium" is a subject a desk asks about; "the
#: calendar spread" is the board's own price structure. POSITIONING IS A SUBJECT TOO and stays
#: eligible by name (D18 and the owner's own scenario, "why are many agri contracts long in managed
#: money"): ``cot_mm_positioning`` is typed ``instrument`` on some boards and ``positioning`` on
#: others, and ``config_check.check_subject_resolver`` clause (14) asserts the fence swallows none of
#: the five positioning ids.
#:
#: IT IS AN ENUM FENCE AND NOT A PROMPT ONE, BECAUSE THE PROMPT WAS TRIED AND THEN MEASURED. The
#: frozen block's v2 says in as many words that a market's own price, spread, curve, basis, roll or
#: front month names no subject "even where the enum carries an id by that name" -- and on phase C's
#: billed layer 2 the planner picked ``calendar_spread`` on four decoy rows and ``basis`` on two
#: anyway (dc08 / dc17 / dc22 / dc25 and dc16 / dc21; 13 of the 16 decoy draws that picked anything).
#: Prose cannot outrank an enum that offers the id, so the id leaves the enum.
#:
#: WHERE THE FENCE LANDS -- THREE SEAMS, AND NOWHERE ELSE. :func:`live_ids` (the enum the orchestrator
#: threads, which ``dispatch._validate`` re-verifies a reply against, so a fenced id is dropped twice
#: over), :func:`hints_line` (the one line the planner reads) and :meth:`SubjectHints.ambiguous` (the
#: carry that interrupts a reader). THE TIERS STILL SEE THE IDS: :func:`exact_ids`, :func:`alias_ids`
#: and :func:`semantic_candidates` range over :func:`all_ids`, so a phrase that says "basis" still
#: records its T0 hit on the trace and a census can count how often the fence had something to do.
#: :func:`groups` and :func:`expand_group` are unfenced for a different reason: a group answers "which
#: boards does this pick open", not "what is this turn about", so a fenced id may still ride a
#: legitimate pick's group as a MEMBER -- ``basis`` sits in ``slice:basis_and_farmer_selling`` with
#: ``sagis_deliveries`` and ``withheld_supply``, and a turn about farmer selling is entitled to the
#: boards that carry it.
OWN_STRUCTURE_IDS: frozenset = frozenset({"calendar_spread", "basis"})

#: THE LINT'S STRONG LEG: a ``silver_ref`` carrying either word measures the ANCHOR'S OWN curve or its
#: own cash-versus-board relationship, however the id happens to be spelled. MEASURED over the whole
#: graph, every type: the only two ids with such a ref are the two in the fence.
_OWN_STRUCTURE_REF_WORDS: tuple = ("calendar", "basis")

#: THE LINT'S WEAK LEG, AND ITS REACH IS STATED RATHER THAN IMPLIED. A bare ``spread`` ref names no
#: market at all, so the ID is the only witness of whether the instrument spans TWO markets or is the
#: anchor's own structure. An id built ENTIRELY from these structural words names none --
#: ``calendar_spread`` is exactly that shape -- while every legitimate cross-market instrument on the
#: shipped graph carries at least one market token (``arabica_robusta_spread``, ``gasoil_palm_spread``,
#: ``rsm_soymeal_spread``, ``white_raw_premium``, ...). MEASURED: ten ids carry a bare-``spread`` ref
#: set and this leg flags ZERO of them, which is the honest reading of what it is for -- a tripwire for
#: the NEXT id named for a structure instead of for two markets. It cannot see an id that names ONE
#: market beside a structural word (a hypothetical ``corn_calendar``), and the strong leg is what
#: catches that class whenever the curation gives it a ref of its own.
_STRUCTURE_WORDS: frozenset = frozenset({
    "spread", "premium", "ratio", "share", "margin", "parity", "competition", "calendar", "basis",
    "price", "floor", "board", "curve", "roll", "front", "month", "carry", "cash", "structure"})

#: THE FROZEN PLANNER SECTION'S SHA -- ``sha256(dispatch._subject_block(<any non-empty vocabulary>))``.
#: The block carries NO substitution at all (the 405-id enum lives in the tool schema, where it is
#: actually binding, and not in the cached prefix), so ONE sha pins it for every roster.
#:
#: WHY THE CONSTANT LIVES HERE AND THE TEXT LIVES IN ``dispatch``: the ``XL_BLOCK_SHA256`` idiom
#: verbatim (that block is in ``dispatch``, its sha in ``numbers/cascade``). A pin in the same file as
#: the text is a pin an editor updates in the same keystroke; a pin one module away is one they must
#: mean to move. ``config_check.check_subject_resolver`` clause (2) grades it, so an edit to the frozen
#: prompt fails the BUILD rather than silently voiding the measurement and consuming the held-out set.
#:
#: V2, 2026-09-10. The FIRST re-freeze, and it is the one this pin exists to make deliberate. Phase B's
#: billed layer 2 measured the v1 text picking a subject on two DECOY rows -- ``calendar_spread`` on a
#: market-structure ask (3 of 3 draws) and ``ending_stocks_su_ratio`` on a how-to-read ask (2 of 3) --
#: which is D9's FATAL bar. v2 adds the two closures those rows name and NOTHING else (+349 ASCII
#: characters, no quoted ask, no question mark); the flag-OFF render is still "" and still byte-
#: identical to HEAD's. v1 was ``39188d42d075f73db9c76a29bed95a53e8dc2442b06bd26e61f5d261a66a2489``
#: and its measurement is banked in :data:`CALIBRATION_NOTE` as v1's, never carried forward as v2's.
SUBJECT_BLOCK_SHA256 = "37900160d21a25445322b01b1420641f9e40398ce3fe6872e66fc522228843bb"

#: The artifact's file name. It lives BESIDE the DAGs it was built from -- ``configs/graphrag/`` is the
#: gitignored overlay the serving image bakes from the live tree, so the artifact rides the SAME image
#: as the graph that produced it and a hash mismatch at load is a stale artifact by construction.
VOCAB_FILENAME = "subject_vocab.npz"

_STATUS_OK, _STATUS_MISSING, _STATUS_STALE, _STATUS_UNREADABLE = "ok", "missing", "stale", "unreadable"

#: Every word :func:`artifact_status` can return. Closed, because the trace and ``config_check`` both
#: read it and a fifth word invented at a call site would reach a census nobody could aggregate.
VOCAB_STATUS_WORDS: tuple = (_STATUS_OK, _STATUS_MISSING, _STATUS_STALE, _STATUS_UNREADABLE)

#: The trace/hint word for a turn on which the semantic tier was never asked to run (no query, or the
#: caller passed no graph). Distinct from a DECLINE: nothing failed.
STATUS_NOT_RUN = "not_run"

#: THE WORD FOR A TIER THAT COULD HAVE RUN AND WAS NOT ASKED TO (D10, 2026-09-10). Two states wear it
#: and both are a DECISION rather than a failure: :func:`resolve` skipped T2 because T0 or T1 already
#: named an id (the question carries a driver's own surface form), or the caller passed
#: ``allow_embed=False`` because its lane will never walk and so nobody would pay the embed back.
#:
#: IT IS A FOURTH KIND OF WORD AND IT IS DELIBERATELY NOT ONE OF THE THREE DECLINE WORDS. ``missing`` /
#: ``stale`` / ``unreadable`` mean THE SHIPPED ARTIFACT AND THE SHIPPED GRAPH DISAGREE, which is what
#: ``BoardSubjectDeclined`` pages on; a skip means the resolver saved a turn 350-550 ms on purpose. A
#: census that could not tell them apart would read every fast turn as a broken build.
STATUS_SKIPPED = "skipped"

#: Every word ``SubjectHints.vocab_status`` can carry, closed and aggregatable: the four the artifact
#: can be in, plus the two that mean the tier never ran. One tuple, so a census can partition a
#: population without knowing which producer wrote the word.
HINT_STATUS_WORDS: tuple = VOCAB_STATUS_WORDS + (STATUS_NOT_RUN, STATUS_SKIPPED)

_VOCAB_CACHE: dict = {}                                    # (path, live_hash) -> loaded dict | None
_FORMS_CACHE: dict = {}                                    # graph identity -> (ids, matchers)
_GROUP_CACHE: dict = {}                                    # graph identity -> {id: group key}


# ---------------------------------------------------------------------------------------------------
# THE ARTIFACT (D7)
# ---------------------------------------------------------------------------------------------------
def vocab_path() -> Path:
    """Where the artifact sits: BESIDE the causal YAMLs, resolved from ``graph``'s own directory
    constant rather than from a second path literal in this file. One producer of "where the DAGs
    live", so an overlay move cannot leave the artifact behind."""
    try:
        from leviathan.graphrag import graph as _G
        return Path(_G._CAUSAL_DIR).resolve().parent / VOCAB_FILENAME
    except Exception:                                      # noqa: BLE001 -- fall back to the tree layout
        return Path(__file__).resolve().parents[4] / "configs" / "graphrag" / VOCAB_FILENAME


def _meta_path(p: Path) -> Path:
    return Path(str(p)[:-4] + ".meta.json") if str(p).endswith(".npz") else Path(str(p) + ".meta.json")


def live_graph_hash(graph=None) -> str:
    """The live graph's content hash. ``graph.version`` when the caller already loaded one (a
    ``CausalGraph.load()`` stamps it from the YAML bytes), else the module's own producer. A synthetic
    test graph carries ``'test'`` or ``None``; both are honest answers and neither is re-derived here."""
    v = getattr(graph, "version", None)
    if v:
        return str(v)
    try:
        from leviathan.graphrag import graph as _G
        return str(_G.causal_graph_version())
    except Exception:                                      # noqa: BLE001 -- no graph is not a crash
        return ""


def artifact_status(path: Optional[Path] = None, *, graph=None) -> tuple:
    """``(status, stamped_hash, live_hash)`` -- the loader's and the lint's ONE question.

    ``missing`` a checkout that never built it (WARN: a working tree is allowed not to carry a 16 MB
    binary); ``stale`` the stamp does not equal the live graph (RED: a DAG edit outran the artifact and
    a silently stale vocabulary resolves ids the graph no longer carries); ``unreadable`` a corrupt
    sidecar; ``ok`` the two hashes agree."""
    p = Path(path) if path is not None else vocab_path()
    live = live_graph_hash(graph)
    meta = _meta_path(p)
    if not p.exists() or not meta.exists():
        return _STATUS_MISSING, "", live
    try:
        import json
        stamped = str(json.loads(meta.read_text(encoding="utf-8")).get("graph_hash") or "")
    except Exception:                                      # noqa: BLE001 -- a corrupt sidecar is a word
        return _STATUS_UNREADABLE, "", live
    if not stamped:
        return _STATUS_UNREADABLE, "", live
    return (_STATUS_OK if stamped == live else _STATUS_STALE), stamped, live


def load_vocab(path: Optional[Path] = None, *, graph=None) -> tuple:
    """``(vocab | None, status)``. ONE ``np.load`` per process per (path, live hash), behind the
    ``server._graph()`` process-cache idiom -- MEASURED at 133-180 ms on a cold OS page cache for the
    25.2 MB float32 array that ships (~153 ms on an independent draw), and at 57.5-63.2 ms (n=5) once
    that file is cached, of which 31.4-38.1 ms is the ``np.load`` itself. The page cache is the
    variable, which is why a RANGE is banked and not a number. Either way it is one load against the
    20-48 MINUTES an in-process boot embed would cost, once per process and outside the per-turn
    budget; every latency figure in :data:`CALIBRATION_NOTE` excludes it.

    The cache key CARRIES THE LIVE HASH, so a graph that moves under a long-lived process re-evaluates
    the stamp instead of serving the vector matrix the previous graph produced. A ``None`` result is
    cached too: a missing artifact must not be stat-ed on every turn."""
    p = Path(path) if path is not None else vocab_path()
    status, _stamped, live = artifact_status(p, graph=graph)
    key = (str(p), live)
    # ONE ENTRY PER PATH, AND THE NEWEST HASH WINS. Without the eviction a graph that moved under a
    # long-lived process would leave the SUPERSEDED vocabulary in this dict for ever -- harmless to
    # this function, which keys on the live hash, but `_loaded_vocab` reads the cache by VALUE for a
    # caller that named no vocabulary, and it would have had two to choose from.
    for _k in [k for k in _VOCAB_CACHE if k[0] == str(p) and k[1] != live]:
        _VOCAB_CACHE.pop(_k, None)
    if key in _VOCAB_CACHE:
        hit = _VOCAB_CACHE[key]
        return (hit, _STATUS_OK) if hit is not None else (None, status)
    if status != _STATUS_OK:
        _VOCAB_CACHE[key] = None
        return None, status
    try:
        import numpy as np
        z = np.load(str(p), allow_pickle=False)             # allow_pickle=False: the artifact is DATA
        V = z["V"]
        ids = [str(x) for x in z["ids"].tolist()]
        fields = [str(x) for x in z["fields"].tolist()]
        texts = [str(x) for x in z["texts"].tolist()]
        if V.ndim != 2 or V.shape[0] != len(ids) or len(fields) != len(ids) or len(texts) != len(ids):
            _VOCAB_CACHE[key] = None
            return None, _STATUS_UNREADABLE
        vocab = {"V": V, "ids": ids, "fields": fields, "texts": texts,
                 "graph_hash": str(z["graph_hash"]), "model": str(z["model"])}
    except Exception:                                      # noqa: BLE001 -- an unreadable artifact is a
        _VOCAB_CACHE[key] = None                           # WORD, never a crash on a serving thread
        return None, _STATUS_UNREADABLE
    _VOCAB_CACHE[key] = vocab
    return vocab, _STATUS_OK


def _reset_caches() -> None:
    """Null the four process caches. For decks and for a graph re-curation inside one process."""
    _VOCAB_CACHE.clear()
    _FORMS_CACHE.clear()
    _GROUP_CACHE.clear()
    _BLURB_CACHE.clear()


# ---------------------------------------------------------------------------------------------------
# THE LIVE ID SET, AND THE ONE SHIPPED MATCHER
# ---------------------------------------------------------------------------------------------------
def all_ids(graph) -> tuple:
    """EVERY driver id the graph declares, sorted -- fence and all. 405 on the shipped 36-contract
    roster (MEASURED).

    THIS IS THE TIERS' POPULATION AND THE GROUP INDEX'S, and :func:`live_ids` is this minus
    :data:`OWN_STRUCTURE_IDS`. The two producers are separate on purpose: a fenced id must still be
    MATCHABLE (a phrase that says "basis" records its T0 hit, and the trace says so) while never being
    SELECTABLE, and one function cannot answer both questions without a caller guessing which it
    got."""
    out = set()
    for cid in getattr(graph, "contracts", {}) or {}:
        try:
            for d in graph.contracts[cid].drivers:
                out.add(str(d.id))
        except Exception:                                  # noqa: BLE001 -- a malformed board is skipped
            continue
    return tuple(sorted(out))


def live_ids(graph) -> tuple:
    """THE ENUM THE PLANNER IS GIVEN: :func:`all_ids` minus :data:`OWN_STRUCTURE_IDS`. 403 of 405 on
    the shipped roster (MEASURED).

    THE ORCHESTRATOR THREADS EXACTLY THIS TUPLE (``dispatch.plan_turn(subject_ids=)``), which mints the
    tool schema's enum AND is what ``dispatch._validate`` re-verifies the reply against -- so a fenced
    id is refused twice: the model is never offered it, and a model that names it anyway has that
    member dropped. ``config_check.check_subject_resolver`` clause (9) already grades that the
    orchestrator threads THIS function and nothing narrower."""
    return tuple(i for i in all_ids(graph) if i not in OWN_STRUCTURE_IDS)


def _instrument_refs(graph) -> dict:
    """``{driver_id: (refs, ...)}`` over the ids the graph types ``instrument`` on ANY board. An id
    typed ``instrument`` on one board and ``positioning`` on another is here -- ``cot_mm_positioning``
    is precisely that -- because the lint's question is about the id's SHAPE and the fence's own
    membership is what decides the rest."""
    out: dict = {}
    for cid in getattr(graph, "contracts", {}) or {}:
        try:
            for d in graph.contracts[cid].drivers:
                if "instrument" not in str(getattr(d, "type", "") or ""):
                    continue
                r = str(getattr(d, "silver_ref", "") or "")
                s = out.setdefault(str(d.id), set())
                if r:
                    s.add(r)
        except Exception:                                  # noqa: BLE001 -- a malformed board is skipped
            continue
    return {i: tuple(sorted(rs)) for i, rs in out.items()}


def own_structure_candidates(graph) -> dict:
    """THE FENCE'S LINT: which instrument-type ids the GRAPH now carries that look like the anchor's
    own price structure, split by whether :data:`OWN_STRUCTURE_IDS` already carries them.

    IT EXISTS BECAUSE A FENCE OF LITERALS GOES STALE IN SILENCE. The set below is two strings; the
    curation that produced them is 36 YAMLs under active edit, and the next ``srw_calendar_spread`` or
    ``gulf_basis`` typed as a driver would land in the planner's enum with nothing to say so. So the
    SHAPE is graded and not the spelling, on two legs whose reach is stated on their own constants:

      strong  any ``silver_ref`` containing ``calendar`` or ``basis`` (:data:`_OWN_STRUCTURE_REF_WORDS`)
              -- the ref MEASURES the anchor's own curve or its own cash-versus-board relationship,
              whatever the id is called.
      weak    a ref set of exactly ``{"spread"}`` -- which names no market -- on an id built entirely
              from :data:`_STRUCTURE_WORDS`. It flags nothing on today's graph and is a tripwire, not
              a census.

    ``{"fenced": (...), "unfenced": (...), "absent": (...), "why": {id: reason}}``. ``unfenced`` is
    what ``config_check.check_subject_resolver`` clause (14) REDS on -- an id the graph declares, the
    lint recognises and the fence does not carry. ``absent`` is a fence entry the graph no longer
    declares, which is advisory (``subject_resolver_warnings``): a curation commit is allowed to
    retire an id, and a fence that outlives one fences nothing rather than breaking anything.

    NOTHING HERE RESOLVES ANYTHING. It is a lint over the graph, called by the build gate and by the
    deck runner's report, and no serving path reads it."""
    refs = _instrument_refs(graph)
    flagged: dict = {}
    for i, rs in sorted(refs.items()):
        low = [r.lower() for r in rs]
        hit = [r for r in low if any(w in r for w in _OWN_STRUCTURE_REF_WORDS)]
        if hit:
            flagged[i] = "silver_ref " + "/".join(sorted(set(hit)))
            continue
        if set(low) == {"spread"} and all(t in _STRUCTURE_WORDS for t in i.lower().split("_") if t):
            flagged[i] = "a bare 'spread' ref on an id built only from structure words"
    declared = set(refs)
    return {"fenced": tuple(sorted(i for i in flagged if i in OWN_STRUCTURE_IDS)),
            "unfenced": tuple(sorted(i for i in flagged if i not in OWN_STRUCTURE_IDS)),
            "absent": tuple(sorted(i for i in OWN_STRUCTURE_IDS if i not in declared)),
            "why": dict(flagged)}


def _graph_key(graph) -> tuple:
    """A cache key for a graph object: its stamped version plus its contract count. The count is there
    because a synthetic deck graph stamps ``'test'`` or ``None`` on every fixture, and two fixtures in
    one process must not share a matcher table."""
    return (str(getattr(graph, "version", "") or ""), len(getattr(graph, "contracts", {}) or {}))


def _id_matchers(graph) -> dict:
    """``{driver_id: matcher}`` over TWO surface forms each -- the id, and its reader form
    ('El_Nino' -> 'El Nino') -- through ``harvest.build_matcher``, the estate's ONE accent/case-folded
    word-boundary matcher. Built once per graph.

    OVER :func:`all_ids`, NOT THE ENUM: T0 is allowed to MATCH a fenced id so the trace can say the
    phrase named one (dc16's "basis" is exactly that row); the fence is applied where the id would
    reach the planner or the reader, never where it would make the record dishonest."""
    key = _graph_key(graph)
    hit = _FORMS_CACHE.get(key)
    ids = all_ids(graph)
    if hit is not None and hit[0] == ids:
        return hit[1]
    from leviathan.graphrag import harvest as hv
    table = {i: hv.build_matcher(sorted({i, i.replace("_", " ")})) for i in ids}
    _FORMS_CACHE[key] = (ids, table)
    return table


def exact_ids(query: str, graph) -> tuple:
    """T0. The ids whose id or reader form the query CONTAINS, most-hits-first then alphabetically --
    ``answer.route_scored``'s own ranking rule, because it is the estate's one ranking for "this
    surface form appears in this question"."""
    q = str(query or "")
    if not q.strip():
        return ()
    scored = []
    for i, m in _id_matchers(graph).items():
        try:
            n = len(m.findall(q))
        except Exception:                                  # noqa: BLE001 -- a matcher is never fatal
            n = 0
        if n:
            scored.append((-n, i))
    scored.sort()
    return tuple(i for _n, i in scored)


def alias_ids(query: str, graph) -> tuple:
    """T1. ``evidence.driver_slices_for(query)`` -> the slices the query's TERMS name -> the DAG ids
    those slices back, INTERSECTED with the live id set and bounded by :data:`HINT_ALIAS_CAP`.

    THE INTERSECTION IS THE POINT. ``evidence.driver_alias()`` returns 424 entries and 127 of them
    point at ids that are in no DAG (MEASURED) -- accent folds and curation drift. An unintersected
    alias would hand the planner an id its own enum does not carry, and downstream ``walk._driver_of``
    swallows an unknown id, so the failure would be a board that anchors nothing with no word for why."""
    q = str(query or "")
    if not q.strip():
        return ()
    try:
        from leviathan.graphrag import evidence as ev
        slices = set(ev.driver_slices_for(q))
        if not slices:
            return ()
        alive = set(all_ids(graph))                        # the TIER's population; the fence is at the
                                                           # three seams, never at the match (see
                                                           # OWN_STRUCTURE_IDS)
        out = sorted({did for did, sl in ev.driver_alias().items()
                      if sl in slices and did in alive})
    except Exception:                                      # noqa: BLE001 -- a config outage declines T1
        return ()
    return tuple(out[:HINT_ALIAS_CAP])


# ---------------------------------------------------------------------------------------------------
# T2 -- THE SEMANTIC TIER
# ---------------------------------------------------------------------------------------------------
def semantic_candidates(query: str, graph, *, embed_fn=None, vocab=None, path: Optional[Path] = None,
                        floor: Optional[float] = None, top_k: int = TOP_K) -> tuple:
    """``(candidates, status)`` where a candidate is ``(driver_id, score, field)``.

    ``embed_fn`` and ``vocab`` are INJECTION SEATS and nothing else: the suite runs with fake vectors so
    no unit test loads a 2 GB model, and the calibration harness passes the real artifact once. Neither
    is a configuration -- production passes neither and gets ``evidence.embed`` and the process cache.

    THE SCORE IS THE MAX OVER THE ID'S ROWS. Not a mean: ``El_Nino`` carries 35 distinct blurbs and a
    mean over them scores the estate's most-shared driver below a driver that appears once."""
    if vocab is None:
        vocab, status = load_vocab(path, graph=graph)
        if vocab is None:
            return (), status
    else:
        status = _STATUS_OK
    q = str(query or "")
    if not q.strip():
        return (), STATUS_NOT_RUN
    try:
        import numpy as np
        if embed_fn is None:
            from leviathan.graphrag import evidence as ev
            embed_fn = ev.embed
        # THE VERBATIM QUERY, and it is the whole latency design: `evidence._Q_CACHE` is keyed
        # (backend, text) and `planner._parallel_fill` pre-warms exactly this key once per turn, so
        # this call is a dict hit. A subject SPAN would be a new key at a MEASURED +350-550 ms.
        qv = np.asarray(embed_fn([q])[0], dtype="float32")
        V = vocab["V"]
        if qv.ndim != 1 or qv.shape[0] != V.shape[1]:
            return (), _STATUS_UNREADABLE
        n = float(np.linalg.norm(qv)) or 1.0
        s = V @ (qv / n)                                   # the artifact's rows are unit-norm already
    except Exception:                                      # noqa: BLE001 -- the embedder is allowed to
        return (), _STATUS_UNREADABLE                      # be gone; T0/T1 are the fail-open floor
    cut = CAND_FLOOR if floor is None else float(floor)
    best: dict = {}
    ids, fields = vocab["ids"], vocab["fields"]
    for r in range(len(ids)):
        sc = float(s[r])
        cur = best.get(ids[r])
        if cur is None or sc > cur[0]:
            best[ids[r]] = (sc, fields[r], r)
    alive = set(all_ids(graph)) if graph is not None else None   # the TIER's population, not the enum
    rows = [(sc, i, fl, r) for i, (sc, fl, r) in best.items()
            if sc >= cut and (alive is None or i in alive)]
    rows.sort(key=lambda t: (-t[0], t[1]))                 # score desc, then id -- fully deterministic
    return tuple((i, round(sc, 6), fl) for sc, i, fl, _r in rows[:max(0, int(top_k))]), status


# ---------------------------------------------------------------------------------------------------
# SUBJECT GROUPS (D4)
# ---------------------------------------------------------------------------------------------------
def groups(graph) -> dict:
    """``{driver_id: group_key}`` over every live id. TWO KEYS, in this order:

    1. THE ``driver_slices`` SLICE the id resolves to (``evidence.driver_alias`` -- the ``dag_alias``
       block IS the estate's curated synonym-set table). Reaches 297 of 405 ids. MEASURED: 128 distinct
       slices, 61 of them carrying more than one id, 230 ids inside a multi-id slice.
    2. For the 108 ids no slice covers, the id's ``silver_ref`` SET -- the feature/metric name that
       MEASURES the driver (``causal/schema.py:48``), present on 1,246 of 1,270 instances and on all 108
       of these.

    THE SET, NOT ANY ONE MEMBER, and the choice is measured rather than argued. Nine of the 108
    uncovered ids carry more than one ``silver_ref``, so a key had to be chosen for them. Union-find
    over the individual refs bridges groups through those nine: 16 groups over 63 ids with a worst-case
    board width of 26. The ref-SET key gives 16 groups over 55 ids at a worst-case width of 18, and it
    separates ``export_pace``/``us_export_pace`` (both ``esr_exports``+``export``) from the five ids
    carrying ``export`` alone. Tighter on every measure, so it is the one that ships.

    THE WRONG MERGES ARE A CURATION FINDING AND NOT A THRESHOLD (D4's own word), AND THE CENSUS THAT
    SURFACES THEM RUNS ON BOTH KEYS -- :func:`merge_census`, which is where the named lists live.
    Seven of the sixteen ``silver_ref`` groups key on a GENERIC balance-sheet attribute -- ``export``,
    ``import``, ``stock``, ``price``, ``production``, ``consumption``, ``area`` -- so they merge ids
    that share a measurement and not a concept. But the SLICE key is the primary one (297 of 405 ids
    against 108) and it carries the merges with teeth: MEASURED, ELEVEN slice groups and THREE ref
    groups merge members carrying OPPOSITE signs on one board (``ref:iod_climate`` merges
    ``IOD_positive`` with ``IOD_negative``; ``slice:biennial_bearing`` merges a coffee cycle's on-year
    with its off-year), and 26 slice groups carry four ids or more, which is a TOPIC family and not a
    synonym set (four pest complexes, ``slice:black_sea_corridor`` at eleven, ``slice:tariff`` at ten).
    Both censuses are banked by NUMBER and by NAME in ``test_subject_resolver.py`` and docketed. The
    fence that bounds the harm already exists and is graded on every tier: ``BoardKnobs.max_anchors``.

    OVER :func:`all_ids`: the group index answers "which boards does this pick open", which is a
    question about the GRAPH and not about the enum, so it stays complete. A fenced id therefore keeps
    its group key -- which is what lets :meth:`SubjectHints.ambiguous` de-duplicate a candidate list
    that still contains one, and what keeps ``group_census``'s banked numbers a census of the graph
    rather than of the fence."""
    key = _graph_key(graph)
    ids = all_ids(graph)
    hit = _GROUP_CACHE.get(key)
    if hit is not None and hit[0] == ids:
        return dict(hit[1])
    alive = set(ids)
    slice_of: dict = {}
    try:
        from leviathan.graphrag import evidence as ev
        slice_of = {did: sl for did, sl in ev.driver_alias().items() if did in alive}
    except Exception:                                      # noqa: BLE001 -- no slices: every id is its
        slice_of = {}                                      # own group, which is the honest fallback
    refs: dict = {}
    for cid in getattr(graph, "contracts", {}) or {}:
        try:
            for d in graph.contracts[cid].drivers:
                r = str(getattr(d, "silver_ref", "") or "")
                if r:
                    refs.setdefault(str(d.id), set()).add(r)
        except Exception:                                  # noqa: BLE001
            continue
    out: dict = {}
    for i in ids:
        sl = slice_of.get(i)
        if sl:
            out[i] = "slice:" + str(sl)
            continue
        rs = tuple(sorted(refs.get(i, ())))
        out[i] = ("ref:" + "+".join(rs)) if rs else ("id:" + i)
    _GROUP_CACHE[key] = (ids, dict(out))
    return out


def group_members(graph) -> dict:
    """``{group_key: (ids, ...)}`` -- :func:`groups` inverted, every member sorted."""
    inv: dict = {}
    for i, k in groups(graph).items():
        inv.setdefault(k, []).append(i)
    return {k: tuple(sorted(v)) for k, v in inv.items()}


def expand_group(ids, graph) -> tuple:
    """The picked ids expanded to every member of their groups, sorted, deduped.

    THIS IS THE OWNER'S "the boards union": the planner picks ONE id, the resolver hands the walk the
    whole synonym set, and the walk anchors every contract carrying any of them (Amendment 1's
    ``focus_driver`` shape). An id the graph does not carry expands to nothing rather than to itself."""
    gm = group_members(graph)
    g = groups(graph)
    out: set = set()
    for i in ids or ():
        k = g.get(str(i))
        if k is None:
            continue
        out |= set(gm.get(k, (str(i),)))
    return tuple(sorted(out))


def group_census(graph) -> dict:
    """The census the tests bank (D4: "MEASURE the groups the two keys produce"). Pure counts, no I/O
    beyond the graph and the slices, so a deck can pin every number without a model or a database.

    IT COUNTS THE GRAPH, NOT THE ENUM (:func:`all_ids`), so the banked numbers move when the CURATION
    moves and stay still when the fence does."""
    gm = group_members(graph)
    ids = all_ids(graph)
    by_slice = {k: v for k, v in gm.items() if k.startswith("slice:")}
    by_ref = {k: v for k, v in gm.items() if k.startswith("ref:")}
    by_id = {k: v for k, v in gm.items() if k.startswith("id:")}
    widths = {}
    for k, members in gm.items():
        boards = set()
        for cid in getattr(graph, "contracts", {}) or {}:
            try:
                if any(d.id in members for d in graph.contracts[cid].drivers):
                    boards.add(cid)
            except Exception:                              # noqa: BLE001
                continue
        widths[k] = len(boards)
    multi = {k: v for k, v in gm.items() if len(v) > 1}
    return {
        "ids": len(ids),
        "groups": len(gm),
        "slice_keyed_ids": sum(len(v) for v in by_slice.values()),
        "ref_keyed_ids": sum(len(v) for v in by_ref.values()),
        "self_keyed_ids": sum(len(v) for v in by_id.values()),
        "slice_groups": len(by_slice),
        "ref_groups": len(by_ref),
        "multi_groups": len(multi),
        "multi_ids": sum(len(v) for v in multi.values()),
        "largest_group": max((len(v) for v in gm.values()), default=0),
        "widest_group_boards": max(widths.values(), default=0),
        "singletons": sum(1 for v in gm.values() if len(v) == 1),
    }


#: A group at or above this many ids is a TOPIC FAMILY candidate rather than a synonym set. Four is
#: the smallest width at which the estate's own merges stop being spellings of one thing: MEASURED,
#: ``slice:rice_blast_pest_complex`` merges four DISTINCT organisms (rice blast, brown planthopper,
#: sheath blight, bacterial leaf blight) and ``slice:black_sea_corridor`` merges eleven ids across
#: two countries and four crops. It is a CENSUS threshold and never a resolver one -- nothing in the
#: resolution path reads it.
WIDE_GROUP = 4


def merge_census(graph) -> dict:
    """THE WRONG-MERGE CENSUS (D4: "Any pair that the census shows to be a wrong merge is a curation
    finding for the docket, never a threshold"), RUN ON BOTH KEYS.

    IT EXISTS BECAUSE THE FIRST CENSUS WAS RUN ON THE MINORITY KEY. :func:`group_census` counts the
    groups and the first docket named the seven generic ``silver_ref`` merges -- 108 of 405 ids. The
    SLICE key is the primary one (297 of 405) and it is where the harmful merges are, because
    ``driver_slices.yaml``'s ``dag_alias`` block was curated to route CORPUS PROPOSITIONS into a slice,
    which is a TOPIC relation, and D4 reads it as a SYNONYM-SET table, which is an identity relation.
    Those two agree on ``fertilizer_cost``/``fertilizer_costs`` and disagree on the three classes below.

    THE THREE CLASSES, each mechanical, each measured off the graph's own declared fields:

      ``sign_flip``   two members carry OPPOSITE signs (``+`` and ``-``) on the SAME board. This is the
                      class with teeth: ``ref:iod_climate`` merges ``IOD_positive`` with
                      ``IOD_negative``, so a pick of either anchors all eighteen boards under the
                      opposite phase, and ``slice:biennial_bearing`` merges the on-year with the
                      off-year of one coffee cycle.
      ``type_mixed``  members declare different ``Driver.type`` words. Weak on its own -- the estate
                      carries 34 type words with many near-synonyms (``macro``/``macro_driver``/
                      ``macro_fx``), which the recon measured and warned not to weight -- so it is
                      reported as a REVIEW list and never as a defect count.
      ``wide``        a group of :data:`WIDE_GROUP` ids or more: a TOPIC family rather than a synonym
                      set. Four pest complexes and two trade families are what this surfaces.

    NOTHING HERE CHANGES A RESOLUTION. It is a report, banked by the deck so a curation commit that
    fixes one of these shows up as a NUMBER moving rather than as a silent improvement, and the fence
    that bounds the harm meanwhile is the one that already exists and is graded on every tier:
    ``BoardKnobs.max_anchors``."""
    gm = group_members(graph)
    inst: dict = {}
    for cid in getattr(graph, "contracts", {}) or {}:
        try:
            for d in graph.contracts[cid].drivers:
                inst.setdefault(str(d.id), {})[cid] = (str(getattr(d, "sign", "") or ""),
                                                       str(getattr(d, "type", "") or ""))
        except Exception:                                  # noqa: BLE001 -- a malformed board is skipped
            continue
    sign_flip, sign_mixed, type_mixed, wide = [], [], [], []
    for k, members in sorted(gm.items()):
        if len(members) < 2:
            continue
        per_board: dict = {}
        for m in members:
            for b, (s, _t) in inst.get(m, {}).items():
                if s:
                    per_board.setdefault(b, set()).add(s)
        signs = [v for v in per_board.values()]
        if any({"+", "-"} <= v for v in signs):
            sign_flip.append(k)
        elif any(len(v) > 1 for v in signs):
            # A SECOND, WEAKER READING KEPT SEPARATE: `0` beside `+` or `-` is a driver declared to
            # have no directional sign on that board, which is a curation question of a different kind
            # from a phase merged with its own opposite. Counted, never folded into the first number.
            sign_mixed.append(k)
        if len({t for m in members for (_s, t) in inst.get(m, {}).values() if t}) > 1:
            type_mixed.append(k)
        if len(members) >= WIDE_GROUP:
            wide.append(k)

    def _split(names):
        return {"n": len(names), "slice": sum(1 for k in names if k.startswith("slice:")),
                "ref": sum(1 for k in names if k.startswith("ref:")), "names": tuple(names)}

    return {"multi_groups": sum(1 for v in gm.values() if len(v) > 1),
            "sign_flip": _split(sign_flip), "sign_mixed": _split(sign_mixed),
            "type_mixed": _split(type_mixed), "wide": _split(wide)}


# ---------------------------------------------------------------------------------------------------
# THE HINTS
# ---------------------------------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class SubjectHints:
    """What the three tiers produced, and nothing more. NOT a decision: the planner decides.

    ``vocab_status`` is one of :data:`HINT_STATUS_WORDS`, and it is the word the trace and the census
    read -- a declined semantic tier must be distinguishable from a semantic tier that ran and found
    nothing, which is the exact hole 6.7 exists to close one layer down, and from a tier that was
    SKIPPED because a free tier already answered or the lane forbade the embed (D10)."""

    exact: tuple = ()
    alias: tuple = ()
    candidates: tuple = ()            # ((driver_id, score, field), ...) -- score desc, then id
    vocab_status: str = STATUS_NOT_RUN
    ms: float = 0.0
    #: ``((driver_id, group_key), ...)`` for the candidates, stamped by :func:`resolve` from
    #: :func:`groups`. APPENDED AT THE TAIL (the estate's own rule for a field added to a shape other
    #: code constructs), and it exists so :meth:`ambiguous` can de-duplicate BY GROUP without a graph:
    #: the orchestrator calls ``hints.ambiguous()`` with no graph in hand and the D4 key is a property
    #: of the resolution, not of the caller. Empty on a hand-built ``SubjectHints`` -- then the method
    #: de-duplicates by ID alone and says so, which is the honest floor rather than a wrong merge.
    groups: tuple = ()

    def ids(self) -> tuple:
        """Every id any tier named, strongest tier first, deduped. The planner's enum is the full live
        set regardless -- this is what the HINT LINE lists, never a restriction on what may be picked."""
        seen, out = set(), []
        for i in tuple(self.exact) + tuple(self.alias) + tuple(c[0] for c in self.candidates):
            if i not in seen:
                seen.add(i)
                out.append(i)
        return tuple(out)

    def ambiguous(self, floor: float = AMBIG_FLOOR, *, graph=None) -> tuple:
        """The candidates at or above :data:`AMBIG_FLOOR` -- what D5 CARRIES into the answer when the
        planner returns no subject -- FENCED and GROUP-DEDUPED. Empty when the semantic tier declined,
        which is correct: a declined tier proposed nothing, so there is nothing a reader was owed.

        FENCED (:data:`OWN_STRUCTURE_IDS`): the carry is the one row that STOPS a reader and asks them
        a question, and "did you mean the calendar spread" is a question about the board's own price
        structure, which is never the subject. An id the planner may not pick must not be an id the
        reader is asked to choose.

        GROUP-DEDUPED, AND THAT WAS A MEASURED DEFECT RATHER THAN A TIDY-UP. ``render.ABSENCE_WHY``
        says the question may mean "either of two drivers this estate tracks" and the seam's decline
        gate is ``len(amb) >= 2``; both were counting SPELLINGS. MEASURED on phase C's layer 1, deck
        v2 row dc23: ``crush_margin`` 0.7962 and ``crush_margin_expansion`` 0.7803 both clear
        :data:`AMBIG_FLOOR` and are ONE driver -- both are ``ref:crush_margin_z`` -- so the estate's
        only measured carry was a row telling a reader to choose between two names for one thing.
        That is D4's own hazard (near-duplicate ids tie by construction) arriving at D5, and the key
        that closes it is the key D4 already built. The STRONGEST candidate of each group survives,
        because :attr:`candidates` is score-descending and the strongest is the one the reader's own
        words came closest to.

        THE KEY COMES FROM :attr:`groups` (stamped by :func:`resolve`), or from ``graph=`` for a
        caller that has one, or -- with neither -- every id is its own group and the method
        de-duplicates by id alone. A missing key is not a licence to merge."""
        gk = dict(self.groups or ())
        if not gk and graph is not None:
            try:
                gk = {c[0]: groups(graph).get(c[0], "") for c in self.candidates}
            except Exception:                              # noqa: BLE001 -- a hint is never worth a turn
                gk = {}
        out, seen = [], set()
        for c in self.candidates:
            i = str(c[0])
            if float(c[1]) < float(floor) or i in OWN_STRUCTURE_IDS:
                continue
            key = str(gk.get(i) or "") or ("id:" + i)
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return tuple(out)

    def trace(self) -> dict:
        """The ``subject.hints`` sub-dict of ``Board.trace()`` (D8). Scores rounded to three places:
        the trace is read by a human and a census, and six places of a float32 cosine is noise."""
        return {"exact": list(self.exact), "alias": list(self.alias),
                "candidates": [[c[0], round(float(c[1]), 3), c[2]] for c in self.candidates],
                "vocab_status": self.vocab_status, "ms": round(float(self.ms), 1)}


def resolve(query: str, *, graph, embed_fn=None, vocab=None, path: Optional[Path] = None,
            top_k: int = TOP_K, allow_embed: bool = True) -> SubjectHints:
    """Run the tiers over one query. NEVER RAISES -- ``SubjectHints()`` is the floor.

    THE ORDER IS THE FAIL-OPEN ORDER: T0 and T1 need no artifact and no embedder and cost a MEASURED
    p50 5.76 / p90 6.97 ms between them, so they run FIRST and their output survives every failure the
    semantic tier can have.

    **T2 IS CONDITIONAL, AND THAT IS THE D10 DECISION TAKEN AT THE CALL SITE (2026-09-10).** The tier
    runs only when the tiers named in :data:`T2_GATE_TIERS` found NOTHING -- T0 and T1 as shipped --
    and ``allow_embed=False`` refuses it outright. Both gates exist because the banked latency figure
    was measured in the wrong state: ``resolve()`` p50 13.44 /
    p90 16.24 ms is the cost with the query ALREADY in ``evidence._Q_CACHE``, and the resolver's real
    seat is BEFORE ``dispatch.plan_turn`` -- before the planner, before the walk, before anything has
    warmed that key. The first call of a turn therefore pays a COLD encode, MEASURED on this box at
    p50 351.34 / p90 387.35 ms (n=40, the deck's own phrases, the memo cleared between draws), which
    is 2.3-2.6x the whole 150 ms budget on its own.

    WHO PAYS IT BACK DECIDES WHETHER IT COSTS ANYTHING. On a lane that walks, the walk re-embeds the
    SAME verbatim query and hits the memo this call just filled, so the turn's total is unchanged and
    the resolver has only moved the cost earlier (MEASURED: the walk's own first embed is the same
    ``(backend, text)`` key -- the walk's own embed after this call MEASURED **0.007 ms**). On a lane
    that never walks -- ``numbers_only``, ``trivial`` -- nobody pays it back and the 350 ms is pure
    addition, so a caller that already knows its lane will not walk passes ``allow_embed=False`` and
    gets T0 and T1 for a MEASURED p50 5.76 / p90 6.97 ms, inside the budget with 143 ms to spare.

    THE ORCHESTRATOR DOES NOT KNOW THE LANE AT THIS POINT, AND THAT IS THE HONEST STATEMENT OF THE
    PROBLEM: ``resolve()`` is called to BUILD the hint line that ``plan_turn`` reads, and the lane is
    the planner's own output, so the knob cannot be set from the plan that has not been made. The two
    ways out are measured in :data:`CALIBRATION_NOTE` and the RECOMMENDATION is the first: pay the
    cold embed once on the lanes that reach the planner at all, because it is the same cache key the
    walk needs and the net cost on a walking lane is ~0; pass ``allow_embed=False`` only where a lane
    is decided BEFORE the planner runs (D-AM-1's price tiebreak and the trivial router both are). The
    second way out -- gating the tier behind a lexical pre-check -- is what :data:`T2_GATE_TIERS`
    already does, and its price is measured there at 5 of 90 calibration rows and 14 of 92 held-out
    rows, which is why it is the alternative and not the recommendation.

    A SKIPPED TIER SAYS SO: ``vocab_status`` is :data:`STATUS_SKIPPED`, which is neither ``ok`` nor one
    of the three decline words, so a census can tell a saved embed from a broken artifact."""
    t0 = time.perf_counter()
    ex = al = cands = gk = ()
    status = STATUS_NOT_RUN
    try:
        ex = exact_ids(query, graph)
        al = tuple(i for i in alias_ids(query, graph) if i not in set(ex))
        gate = tuple(T2_GATE_TIERS)
        lexical = (ex if "exact" in gate else ()) + (al if "alias" in gate else ())
        if not str(query or "").strip():
            status = STATUS_NOT_RUN                        # nothing to run ON, which is not a skip
        elif not allow_embed or lexical:
            status = STATUS_SKIPPED
        else:
            cands, status = semantic_candidates(query, graph, embed_fn=embed_fn, vocab=vocab,
                                                path=path, top_k=top_k)
            # THE D4 KEY, STAMPED WHERE THE GRAPH IS IN HAND. `ambiguous()` de-duplicates by GROUP and
            # its production caller (`orchestrator.py`, after `plan_turn`) has no graph, so the key
            # travels with the hints rather than being re-derived from a graph the carry does not
            # hold. `groups()` is process-cached per graph, so this costs a dict lookup per candidate.
            if cands:
                _gmap = groups(graph)                      # ONE call: `groups` returns a COPY of a
                _gmap = _gmap if isinstance(_gmap, dict) else {}   # 405-entry dict on every call
                gk = tuple((c[0], str(_gmap.get(c[0]) or "")) for c in cands)
    except Exception:                                      # noqa: BLE001 -- a resolver failure must
        pass                                               # never break a turn (seam.py's precedent)
    return SubjectHints(exact=tuple(ex), alias=tuple(al), candidates=tuple(cands),
                        vocab_status=status, ms=(time.perf_counter() - t0) * 1000.0,
                        groups=tuple(gk))


def _reader_name(driver_id: str) -> str:
    """A driver id as reader words through the estate's ONE display vocabulary
    (``state.render.humanise`` -> ``display.node_label``), ASCII-folded. Never a second table."""
    try:
        from leviathan.graphrag.state import render as R
        return R.humanise(str(driver_id))
    except Exception:                                      # noqa: BLE001 -- the id is the last resort
        return str(driver_id).replace("_", " ")


def _blurbs_for(wanted: dict, vocab) -> dict:
    """``{driver_id: one short piece of that driver's OWN prose}`` for the hint line.

    ONE PASS OVER THE ARTIFACT FOR ALL CANDIDATES, not one per candidate: the matrix carries 4,000 rows
    and a per-candidate scan is five of them for a line that must cost single-digit milliseconds.

    THE BLURB IS PREFERRED OVER THE ROW THAT ACTUALLY MATCHED, and that is a reader decision rather
    than a retrieval one. ``Driver.blurb`` is the schema's own "<=15-word plain-English tooltip"; the
    other three fields are not written to be read -- MEASURED on the first line this produced, where
    ``El_Nino`` won on its ``evidence_query`` and the hint read "El Nino ONI Colombia coffee drought
    Brazil rainfall arabica impact", which is a keyword soup a planner has to decode rather than a
    description it can weigh. The winning row's own text is the fallback for an id with no blurb, and
    the ``id`` field is never shown because the line already prints the reader name.

    THE FIRST BLURB IN SORT ORDER, deterministically: an id carries a different blurb on each board it
    sits on (166 of 405; ``El_Nino`` carries 35 distinct ones), so "the blurb" is a choice and it is
    made here once rather than by whichever board happened to be read first.

    THE INDEX IS BUILT ONCE PER PROCESS, NOT ONCE PER TURN. "One pass over the artifact" is still four
    thousand Python-level rows, and once the line's ``vocab`` default became the real artifact that
    pass MEASURED 33 ms p50 / 62 ms p90 -- more than the whole rest of the resolver put together. The
    per-id index is a few hundred short strings, it is derived from an immutable file, and it is keyed
    the way :func:`load_vocab`'s own cache is."""
    if not vocab or not wanted:
        return {}
    idx = _blurb_index(vocab)
    out = {}
    for d, want in wanted.items():
        row = idx.get(d) or {}
        out[d] = row.get("blurb") or (row.get(want, "") if want not in ("id", "blurb") else "")
    return out


_BLURB_CACHE: dict = {}                                    # vocabulary identity -> {id: {field: text}}


def _blurb_index(vocab) -> dict:
    """``{driver_id: {field: text}}`` over the whole artifact, ONE pass, process-cached. The ``blurb``
    entry is the lexicographically first of that id's blurbs (the determinism :func:`_blurbs_for`
    owes); every other field keeps the first row in artifact order, which is the producer's own."""
    key = (str(vocab.get("graph_hash") or ""), str(vocab.get("model") or ""), len(vocab["ids"]))
    hit = _BLURB_CACHE.get(key)
    if hit is not None:
        return hit
    ids, fields, texts = vocab["ids"], vocab["fields"], vocab["texts"]
    idx: dict = {}
    for r in range(len(ids)):
        row = idx.setdefault(ids[r], {})
        f, t = fields[r], str(texts[r])
        if f == "blurb":
            if "blurb" not in row or t < row["blurb"]:
                row["blurb"] = t
        elif f not in row:
            row[f] = t
    _BLURB_CACHE[key] = idx
    return idx


#: The ``vocab`` default for :func:`hints_line`: LOAD THE ARTIFACT. Distinct from ``None``, which is
#: an explicit "no prose available, print the line without blurbs" -- the two are different states and
#: a single ``None`` could not tell them apart.
_LOAD_VOCAB = object()


def _loaded_vocab():
    """The artifact for a caller that named none -- THIS PROCESS'S ALREADY-LOADED ONE FIRST.

    THE RE-VALIDATION IS THE EXPENSIVE PART, NOT THE LOAD. ``load_vocab()`` with no graph asks
    ``graph.causal_graph_version()`` for the live hash, and that re-reads and re-hashes all 36 causal
    YAMLs on every call -- MEASURED 18.8 ms, against 0.2 ms for the whole rest of this line. The turn
    has ALREADY answered that question: :func:`resolve` ran moments earlier with the live graph in
    hand, where the identity is ``graph.version`` and costs nothing. So a vocabulary already in the
    process cache is taken as-is; only a cold call -- a caller that renders a line without having
    resolved one -- pays the full check, and it pays it once."""
    for v in _VOCAB_CACHE.values():
        if v is not None:
            return v
    try:
        v, _st = load_vocab()
        return v
    except Exception:                                      # noqa: BLE001 -- a hint is never worth a turn
        return None


def hints_line(hints: SubjectHints, *, vocab=_LOAD_VOCAB, max_blurb: int = 90) -> str:
    """THE ONE LINE THAT REACHES THE PLANNER, and it reaches it in the USER MESSAGE only.

    ``vocab`` DEFAULTS TO LOADING THE ARTIFACT, and that default is a promise the FROZEN block makes on
    this function's behalf: it tells the planner to expect "nearest matches by meaning with each
    driver's one-line description". With ``vocab=None`` this function printed no description at all,
    so a caller that forgot the argument would have shipped a prompt promising a field the line never
    carried -- and correcting the PROMPT instead would VOID the freeze and consume the held-out set.
    It resolves through :func:`_loaded_vocab`, which takes the artifact the turn's own
    :func:`resolve` already loaded, so the default costs a dict lookup and not a re-validation; a
    missing or stale artifact yields ``None`` and the line degrades to names and scores, which is the
    same fail-open floor the semantic tier itself takes. Pass ``vocab=None`` to ask for that floor
    deliberately, or a loaded vocabulary to pin one. MEASURED with blurbs, warm: p50 0.38 / p90 0.52 ms.

    NEVER THE SYSTEM BLOCK. The planner's system prompt is the cached prefix
    (``dispatch._SYS_RENDERS`` memoizes an unchanged render to the SAME object precisely so an unmoded
    turn's prefix is byte-identical); per-turn text there would bust that cache on EVERY turn, which is
    a real bill for a hint. The user message is already per-turn.

    ASCII AND DETERMINISTIC. The names come from the display vocabulary and are folded; the order is
    exact, then alias, then candidates by score descending and id ascending. Empty hints render ``""``
    and the caller omits the line entirely -- the omit-when-off idiom, one layer up."""
    if not isinstance(hints, SubjectHints):
        return ""
    # THE FENCE, AT THE ONE LINE THE PLANNER READS (:data:`OWN_STRUCTURE_IDS`). The enum already
    # refuses these ids; a hint line that still NAMED one would spend a slot advertising an id the
    # schema forbids and the validator drops -- and phase C measured what an offered id does to a
    # market-structure ask. The tiers keep their own record: `hints.exact` still carries the T0 match
    # and the trace still prints it, so a census can count the phrases the fence had work to do on.
    # A LINE THAT LOSES EVERY PART RENDERS "", which is the same omit-when-empty the caller already
    # honours.
    ex = tuple(i for i in hints.exact if i not in OWN_STRUCTURE_IDS)
    al = tuple(i for i in hints.alias if i not in OWN_STRUCTURE_IDS)
    cd = tuple(c for c in hints.candidates if str(c[0]) not in OWN_STRUCTURE_IDS)
    parts = []
    if ex:
        parts.append("exact " + ", ".join(f"{_reader_name(i)} [{i}]" for i in ex))
    if al:
        parts.append("alias " + ", ".join(f"{_reader_name(i)} [{i}]" for i in al))
    if cd:
        # THE LOAD IS TAKEN HERE AND NOWHERE ELSE: only the CANDIDATE chunks carry a blurb, so a turn
        # whose hints are exact/alias-only -- and an empty-hints call, which is the common one -- never
        # touches the artifact at all.
        if vocab is _LOAD_VOCAB:
            vocab = _loaded_vocab()
        blurbs = _blurbs_for({c[0]: c[2] for c in cd}, vocab)
        chunks = []
        for did, score, _field in cd:
            blurb = str(blurbs.get(did) or "").strip().replace("\n", " ")
            if len(blurb) > max_blurb:
                blurb = blurb[:max_blurb].rstrip() + "..."
            chunks.append(f"{_reader_name(did)} [{did}] {float(score):.2f}"
                          + (f" -- {blurb}" if blurb else ""))
        parts.append("candidates " + "; ".join(chunks))
    if not parts:
        return ""
    line = "subject hints: " + " | ".join(parts)
    try:
        from leviathan.graphrag.state.render import ascii_text
        line = ascii_text(line)
    except Exception:                                      # noqa: BLE001 -- fold by hand as a floor
        line = "".join(c if ord(c) < 128 else " " for c in line)
    return " ".join(line.split())


__all__ = ["CAND_FLOOR", "AMBIG_FLOOR", "TOP_K", "HINT_ALIAS_CAP", "T2_GATE_TIERS",
           "SUBJECT_BLOCK_SHA256", "OWN_STRUCTURE_IDS",
           "VOCAB_FILENAME", "VOCAB_STATUS_WORDS", "STATUS_NOT_RUN", "STATUS_SKIPPED",
           "HINT_STATUS_WORDS", "WIDE_GROUP", "SubjectHints",
           "artifact_status", "load_vocab", "vocab_path", "live_graph_hash", "all_ids", "live_ids",
           "own_structure_candidates",
           "exact_ids", "alias_ids", "semantic_candidates", "groups", "group_members",
           "group_census", "merge_census", "expand_group", "resolve", "hints_line"]


# ---------------------------------------------------------------------------------------------------
# THE CALIBRATION TABLE (D9, layer 1) -- BANKED HERE AND IN THE DECK HEADER
# ---------------------------------------------------------------------------------------------------
#: The frozen measurement the two floors above were chosen on. It is a STRING and not a test because a
#: test would need the 25 MB artifact and a 120 s model load; the runnable half lives at
#: ``scratchpad/subjcal/calibrate.py`` and its output is reproduced here verbatim so a reader of this
#: module never has to go looking for the numbers a constant was chosen from.
CALIBRATION_NOTE = """LAYER 1, frozen 2026-09-09, RE-MEASURED 2026-09-10 by an independent run (every
RATE reproduced exactly; the three score figures below now state their DENOMINATOR, which the first
bank did not). Deck configs/graphrag/subject_deck_v1.yaml (104 rows). Artifact
configs/graphrag/subject_vocab.npz -- graph 99dc11409fe9, 4,000 rows x 1,024, bge-m3, built in 1,814 s.
CAND_FLOOR 0.52, AMBIG_FLOOR 0.78, TOP_K 5. One draw per row (deterministic).

THE DENOMINATOR. A row's top-1 score can be read over the CANDIDATE LIST (ids at or above CAND_FLOOR,
top-5 -- what the planner is shown, and what every RATE below is scored over) or over the FULL 405-id
RANKING (every id, floor -1 -- where a miss's RANK comes from). They differ only on rows carrying no
candidate at all: one synonym row and seven of the fourteen decoys. Both columns are printed, because
a reader who re-derives one figure under the other denominator concludes the instrument moved.

class            n   anyT2   hit@1  all-tiers  med CAND (n)  med FULL   bar      verdict
exact           10   10/10   10/10      10/10   0.756  (10)     0.756   100%     PASS
alias           10    9/10    7/10      10/10   0.649  (10)     0.649   100%     PASS (T1 carries al02)
synonym         14   10/14    7/14      10/14   0.662  (13)     0.654   >= 90%   MISS  (71.4%)
misspelling     14   13/14   13/14      13/14   0.706  (14)     0.706   >= 85%   PASS  (92.9%)
description     14   14/14   10/14      14/14   0.632  (14)     0.632   >= 75%   PASS  (100%)
acronym         10   10/10    7/10      10/10   0.724  (10)     0.724   100%     PASS
near_duplicate  10   10/10    6/10      10/10   0.665  (10)     0.665   top-5    PASS
multi            8     8/8     8/8        8/8   0.717   (8)     0.717   both     PASS
decoy           14  cand=7 carry=0          -   0.586   (7)     0.524   carry=0  PASS (FATAL bar clean)
ALL non-decoy   90   84/90   68/90      85/90
                  =  93.3%   75.6%      94.4%

THE FLOOR-SETTING FIGURES, each with its denominator. Decoy MAX top-1 0.7360 (dc13) -- the SAME under
both, and the only figure AMBIG_FLOOR was chosen on. Decoy top-1 over the CANDIDATE list (n=7):
min 0.5298 / median 0.5863 / sd 0.0653; over the FULL ranking (n=14): min 0.4314 / median 0.5236 /
sd 0.0800. Description-class MIN true score 0.5427 (de04), same under both. Weakest true score of ANY
class: 0.4396 (sy06) over the FULL ranking, 0.5231 (nd03) over the candidate list.

THE NEAR_DUPLICATE BAR IS "the expected GROUP is in the top-5" (10/10). The stricter reading -- "the
resolved id's group EQUALS the expected group" -- is D9's LAYER-2 bar, scored on the planner's own
pick: layer 1 produces a LIST and a list has no single resolved id. The group-equality proxy over
top-1 measures 6/10 and is reported as hit@1, never as this class's verdict.

THE STANDING RISK, NAMED: 7 of 14 decoy rows put a candidate at or above CAND_FLOOR in front of the
planner (0 at AMBIG_FLOOR, so the FATAL bar is clean). That is what D2 accepts -- the planner is the
list's fence -- but what the planner DOES with a hint on a driver-free ask is unmeasured until the
billed layer 2. It is that run's first obligation, not a layer-1 defect.

AGAINST THE BASELINE. The recon measured the shipped lexical driver resolution at 30.0% any-hit /
23.3% hit@1 over thirty synonym+misspelling+description phrases. On the SAME three classes here
(n=42): 88.1% any-hit / 71.4% hit@1 -- 2.9x and 3.1x.

LIKE FOR LIKE, RE-RUN 2026-09-10 ON THOSE THIRTY PHRASES THEMSELVES (recon rows sy01-de10) rather than
on a same-class sample, both legs scored by one rule against each row's own expected ids:

  the SHIPPED driver matcher (driver_slices_for -> driver_alias, which IS T1)  9/30  30.0%   7/30  23.3%
  the strongest lexical variant the recon could build (+ id surface forms)    11/30  36.7%   8/30  26.7%
  THE TIERS, T0 + T1 + T2                                                     27/30  90.0%  16/30  53.3%
  THE TIERS with the shipped T2_GATE_TIERS gate                               25/30  83.3%  16/30  53.3%

Both baselines REPRODUCE the recon's banked figures to the row (9/30 = 30.0% / 7/30 = 23.3% and
11/30 = 36.7% / 8/30 = 26.7%), which is what makes the comparison a measurement rather than a quote:
the uplift is 3.0x any-hit and 2.3x hit@1 over the shipped matcher, 2.5x and 2.0x over the strongest
lexical variant anyone could have built without an embedder. Scored group-expanded instead, the tiers
read 27/30 and 18/30; the strict column is printed because the recon's own numbers are strict.

THE HELD-OUT DECK, SCORED 2026-09-10 AND CONSUMED BY IT (D9's protocol: floors frozen first, one
scoring pass, no phrase copied into the tree). 110 rows authored blind against the id list alone,
scored by THIS runner with CAND_FLOOR 0.52 / AMBIG_FLOOR 0.78 / TOP_K 5 unchanged:

class            n   anyT2   hit@1  all-tiers  bar      verdict
synonym         16   13/16    9/16      14/16  >= 90%   MISS (87.5%)
misspelling     18   18/18   15/18      18/18  >= 85%   PASS (100.0%)
description     18   15/18   14/18      16/18  >= 75%   PASS (88.9%)
acronym         16   16/16   14/16      16/16  100%     PASS (100.0%)
multi           12   12/12    7/12      12/12  both     PASS (12/12 groups reached)
near_duplicate  12   10/12    9/12      10/12  top-5    MISS (83.3%)
decoy           18  cand=12 carry=0         -  carry=0  PASS (FATAL bar clean)
ALL non-decoy   92   84/92   68/92      86/92
                  =  91.3%   73.9%      93.5%

IT REPRODUCES THE CALIBRATION WITHIN A POINT (93.3 / 75.6 / 94.4 there against 91.3 / 73.9 / 93.5
here) on rows the floors were NOT chosen on, which is the property a held-out set exists to test, and
the decoy FATAL bar is clean with room: the worst held-out decoy scores 0.6716 against an AMBIG_FLOOR
of 0.78. The two MISSED bars are synonym (14/16) and near_duplicate (10/12), and both miss by ONE ROW
past the bar rather than by a mechanism: 4 of the 6 all-tiers misses put the expected id outside the
top-5 with a best-true score of 0.50-0.57, which is the same paraphrase-matcher limit the calibration
deck's four synonym misses named -- the driver's own prose does not carry the concept the phrase used.
Docketed as curation, with the calibration deck's four.

THE ONE MISSED BAR IS SYNONYM, AND THE MECHANISM IS NAMED. All four misses are phrases that name the
driver by an EXTERNAL concept its own prose never states: sy01 'the pacific warming' (El_Nino is not
in the top FORTY -- no blurb of its 105 rows says Pacific or warming), sy02 'the cold phase in the
tropical pacific' (La_Nina at rank 8), sy06 'the big trend followers' (positioning at rank 14), sy14
'a pig epidemic in China' (ASF_hog_herd at rank 8). The semantic tier is a PARAPHRASE matcher over the
driver's own prose, not a knowledge base -- which is exactly why the class it transforms is
DESCRIPTION (1/10 lexically -> 14/14 here) and exactly why T1 exists. Every one of the four is a
one-line CURATION fix in driver_slices.yaml, not a threshold: 'pacific warming' and 'trend followers'
are terms the el_nino and cftc_positioning slices do not carry. Docketed.

LATENCY (D10, budget <= 150 ms added per turn, p90). RE-MEASURED 2026-09-10 AT THE CALL SITE, and the
first bank was measured in the WRONG STATE. Every figure below is on this CPU box, over the deck's own
phrases, on the real model and the real artifact.

THE STATE IS THE WHOLE MEASUREMENT. The first bank timed the resolver with the query ALREADY in
evidence._Q_CACHE, on the reasoning that planner._parallel_fill pre-warms exactly that key once a turn.
It does -- but the resolver's seat is BEFORE dispatch.plan_turn, which is before the planner and before
the walk, so on the first call of a turn that key is COLD and the resolver, not the walk, is the caller
that fills it. Both populations are therefore printed, and the memo is CLEARED between draws to produce
the cold one rather than inferred from the warm one.

                                                        p50       p90      n
  T2 alone, WARM memo (cosine 4,000x1,024 + max + top-k)    5.45      6.64     40
  T2 alone, COLD memo (the bge-m3 encode + the cosine)    324.40    348.56     40
  resolve() T0+T1+T2, WARM memo -- THE BANKED STATE        11.82     15.36     40
  resolve() T0+T1+T2, COLD memo -- THE CALL SITE          351.34    387.35     40
  resolve(allow_embed=False) -- T0+T1, THE LANE KNOB        5.76      6.97     40
  hints_line() alone, WITH blurbs, default vocabulary        0.26      0.61     40
  the WHOLE 104-row deck, cold memo, T2 CONDITIONAL       304.22    358.45    104

THE LANE SPLIT, AND IT IS THE DECISION. The added wall is 15 ms at p90 when the memo is warm and
387 ms when it is cold -- 10% of the budget against 258% of it -- so D10 is met or violated by WHO ELSE
NEEDS THE SAME KEY, never by the resolver's own arithmetic:

  a lane that WALKS      net ~0. The walk re-embeds the same verbatim query and hits the memo this
                         call filled: MEASURED at 0.007 ms for the walk's own embed after resolve().
                         The turn pays one encode either way; the resolver only pays it earlier.
  a lane that NEVER
  walks (numbers_only,   pure addition, 351 ms p50. This is the lane the knob exists for, and
  trivial)               allow_embed=False is measured at 5.76 / 6.97 ms -- T0 and T1, no embed.
  T0/T1 ANSWERED         44 of the deck's 104 rows (42.3%): no embed at any lane, 5.76 ms p50.

THE ORCHESTRATOR DOES NOT KNOW THE LANE WHEN IT CALLS resolve(), because the lane is plan_turn's own
output and resolve() builds the line plan_turn reads. THE RECOMMENDATION, on these figures, is to PAY
THE COLD EMBED once on every lane that reaches the planner, and to pass allow_embed=False only where a
lane is decided BEFORE the planner runs (D-AM-1's price tiebreak and the trivial router are both such
places). Paying it costs a walking lane ~0 and a non-walking lane 351 ms; gating it behind a second
lexical pre-check costs measured ACCURACY on every lane, which the next paragraph prices.

THE GATE'S PRICE, MEASURED AND NOT ARGUED, ON BOTH DECKS. The shipped conditional rule (T2 runs only
when T0 and T1 found nothing) saves 42.3% of the calibration deck's embeds and 37.3% of the held-out
deck's, and costs FIVE of ninety true calibration rows and FOURTEEN of ninety-two held-out rows their
all-tiers hit: 94.4% -> 88.9% and 93.5% -> 78.3%. Recomputed offline from the banked per-row scores of
each deck, so both are re-reads of one scoring pass and not second runs. Per class on the calibration
deck, all-tiers, UNCONDITIONAL -> CONDITIONAL: synonym 10/14 -> 8/14, misspelling 13/14 -> 12/14,
acronym 10/10 -> 8/10; exact, alias, description, near_duplicate and multi unmoved. Decoy carries at
AMBIG_FLOOR stay ZERO under every rule, so this is a hint-quality trade and never a safety one. The
full three-row decision table and the RECOMMENDATION are on T2_GATE_TIERS, which is the one literal
that moves it.

ONE MECHANISM PRODUCES ALL FIVE, and it is the same curation shape the four synonym misses are:
the lexical tier matches a driver the phrase mentions IN PASSING while the subject is a driver only T2
reaches. sy03 'palm diesel blending target' -> T1 gives gasoil_palm_spread, T2 gives biodiesel_mandate
at 0.662. sy11 'a weaker Brazilian currency' -> T1 gives basis / sagis_deliveries / withheld_supply off
'farmer selling', T2 gives BRL_FX at 0.802, the strongest true score on the deck. ms05 'heat stres
during pod fill' -> T0 EXACT-matches pod_fill, T2 gives heat_stress at 0.703. ac05 'the southern
hemisphere pressure belt' -> T0 matches frost, T2 gives SAM at 0.739. ac06 'the warm Atlantic cycle' ->
T1 gives hurricane_damage, T2 gives AMO at 0.818. THE MIDDLE RULE IS BANKED TOO, for a one-line flip:
gating on T0 ALONE saves 18.3% of embeds and costs TWO rows (ms05, ac05) -- 83/90, 92.2%. Docketed
beside the four synonym misses, because all nine are answered the same way, by a term in
driver_slices.yaml rather than by a threshold.

TWO COSTS ARE OUTSIDE ALL OF THESE, AND BOTH ARE ONCE PER PROCESS: the np.load of the 25.2 MB artifact
and the per-id blurb index built from it (a single pass over 4,000 rows). The load MEASURED 133 / 180 /
166 ms on the 2026-09-09 draws and ~153 ms on an independent 2026-09-10 draw, both on a COLD OS page
cache; re-measured 2026-09-10 with the file already in the page cache it is 57.5-63.2 ms (n=5, of which
31.4-38.1 ms is the np.load itself). The page cache is the variable, so the range and not a single
number is the honest figure, and every per-turn row above excludes it. Both costs were per-CALL in the
first cut of the hint line and MEASURED 33 ms p50 / 62 ms p90 between them -- more than the whole rest
of the resolver -- of which 18.8 ms was graph.causal_graph_version() re-reading and re-hashing all 36
causal YAMLs to re-validate a vocabulary the turn had already loaded.

===================================================================================================
THE v2 ADDENDUM (2026-09-10), after phase B's billed layer 2 STOPPED on the FATAL decoy bar. Three
decisions and one new finding, all on BANKED per-row scores and BANKED draws -- no deck was re-run
for any figure below, and nothing here was billed.

(1) THE HINT FLOOR: CONSIDERED, PRICED, AND REFUSED.
Both of phase B's decoy picks came from candidates in the 0.55-0.56 band, so the obvious lever was a
HINT_FLOOR between CAND_FLOOR and AMBIG_FLOOR: stop SHOWING the planner a candidate that weak. The
rule stated before the arithmetic was "take it only if it costs zero true rows". RECOMPUTED from the
banked per-row scores of BOTH decks (the same re-read the T2 gate's table is built from), all-tiers,
against the 0.52 baseline of 85/90 calibration and 86/92 held-out:

  HINT_FLOOR   calibration all-tiers   true rows lost   held-out all-tiers   true rows lost
  0.52 (none)  85/90  94.4%                       -     86/92  93.5%                     -
  0.58         83/90  92.2%                       2     72/92  78.3%                    14
  0.60         80/90  88.9%                       5     66/92  71.7%                    20
  0.62         76/90  84.4%                       9     61/92  66.3%                    25

NOT TAKEN, at any of the three. The cheapest costs two calibration rows (de04 at 0.5427 and de09 at
0.5756, both description -- the class whose true scores bottom out exactly there) and FOURTEEN
held-out rows across five classes, which is 15.2% of that deck's non-decoy population. It buys 3 of
the 7 calibration decoys that carry a candidate and 4 of the 12 held-out ones, and it does not reach
the second decoy pick AT ALL: dc09's five ids came from the ALIAS tier, which no candidate floor
fences. So the closure belongs where the pick is made -- the frozen block, whose v2 adds the two
sentences those rows named -- and not in a threshold that pays for it out of the description class.
CAND_FLOOR, AMBIG_FLOOR and TOP_K are unmoved.

(2) THE LAYER-2 SCORER WAS WRONG ABOUT `near_duplicate` AND `multi`, AND THE DRAWS PROVE IT.
A row's `expect` list names, for each cause the ask carries, the ids that would EACH be a right
answer for it -- alternatives, not a conjunction. Phase B's scorer read it as a conjunction:
`near_duplicate` demanded `group_keys(pick) == group_keys(expect)` and `multi` demanded every listed
group. But `groups()` is a curated slice index and two slices can hold two spellings of one cause --
nd03's `managed_money_positioning` sits apart from the four `slice:cftc_positioning` spellings, nd10's
`India_export_ban` apart from the other three, and mu02's `Argentina_export_tax` apart from
`export_tax` -- so the old rule asked ONE pick to carry two group keys at once, or asked the planner
to name two spellings of one cause as two subjects, which the frozen block forbids in as many words.
RE-SCORED on phase B's OWN banked draws (scripts/graphrag/subject_deck_run.py --rescore, no call
made): near_duplicate 4/10 -> 10/10, multi 5/8 -> 8/8, all non-decoy 78/90 -> 87/90. Every other
class is unmoved to the row. Both readings print on every run from here. AFTER THE CORRECTION THE
CALIBRATION DECK HAS EXACTLY ONE FAILING LAYER-2 BAR LEFT AND IT IS THE FATAL ONE -- which is what
makes the block's v2 the whole remaining question.

(3) THE v2 DECK'S NEW DECOY SUB-CLASS, MEASURED AT LAYER 1 (free, 2026-09-10, artifact ok, instrument
LIVE on 118 of 118 rows). configs/graphrag/subject_deck_v2.yaml is v1's 104 rows verbatim plus
fourteen decoys of the two shapes the FATAL bar named -- eight market-structure asks and six
how-to/methodology/tool asks. Layer 1 on all 28 decoys: 17 put a candidate above CAND_FLOOR in front
of the planner (7 of them v1's), and ONE carries at AMBIG_FLOOR.

THE ONE CARRY IS A FINDING AND IT IS NOT TUNED AWAY. dc23 -- a methodology ask that names a tracked
quantity by its own reader form -- is EXACT-matched by T0 and its family ranks 0.7962 / 0.7803 /
0.7567 / 0.7352 / 0.7107, two of them above AMBIG_FLOOR 0.78. The deck's L1 DECOY CARRY bar therefore
STOPS on v2, by construction and not by drift: v1's decoy class was "asks that name NO driver" and
0.78 was calibrated on it, while this row names one out loud and asks how it is COMPUTED. That is the
sub-class's whole point at layer 2, and it exposes a seam-level disagreement worth naming:

  a. THE BLOCK AND THE CARRY DISAGREE ON EXACTLY THIS ASK. The v2 block tells the planner to name no
     subject on a how-to-compute question -- and `seam._write_subject`'s carry fires on `amb and not
     picked`, so a planner that obeys is followed by a row asking the reader which driver they meant,
     and on an anchorless board by a `subject_ambiguous` DECLINE. The closure the block makes at the
     pick is undone one layer down.
  b. THE TWO IDS IT WOULD NAME ARE ONE DRIVER. `crush_margin` and `crush_margin_expansion` are both
     `ref:crush_margin_z`. `ambiguous()` is not group-deduped, so the render's sentence -- "either of
     two drivers this estate tracks" -- is untrue on this population, and the decline gate
     `len(amb) >= 2` counts SPELLINGS rather than drivers, which is D4's own hazard arriving at D5.

Both are DOCKETED and neither is fixed here: the fix is in `ambiguous()` and in the seam, and this
sitting's allowlist reaches neither. The L2 decoy bar -- zero picks on any draw across all 28 rows --
is the one the block's v2 is graded on and it is independent of this carry.

===================================================================================================
THE PHASE-D ADDENDUM (2026-09-10). Phase C's billed layer 2 answered the question v2 was written to
ask, and the answer was no: 7 of 28 decoy rows still had the planner pick a subject. Three closures,
all free, none of them a threshold, and the two dockets above are two of them.

(1) THE ENUM FENCE, AND WHY IT IS THE ENUM AND NOT THE PROMPT. Of the seven fires, SIX picked an id
that IS the anchor's own price structure -- `calendar_spread` on dc08/dc17/dc22/dc25 and `basis` on
dc16/dc21 -- while the frozen block already said, in as many words, that a market's own price,
spread, curve, basis, roll or front month names no subject "even where the enum carries an id by that
name". That sentence is the strongest form the prose can take; the measurement says it does not beat
an enum that offers the id. So :data:`OWN_STRUCTURE_IDS` leaves the enum, the hint line and the carry
(the three seams; the TIERS still match, so the trace still says the phrase named one), and
`dispatch._validate` drops a fenced id from a reply that names one anyway.

THE RE-SCORE OF PHASE C's OWN BANKED DRAWS, free and offline (`--rescore`, no call made; banked at
data/subject_resolver/2026-09-10/subject_deck_v2_fence_rescore.json and pinned by `test_pd7`):

  decoy ROWS that picked a subject      7 of 28   -> fence removes 6, leaving 1 (dc18)
  decoy DRAWS that picked a subject    16 of 84   -> fence removes 13, leaving 3
  true rows losing an EXPECTED id       0 of 90
  true rows losing a SPURIOUS 2nd pick  2 (ex06, al05: `basis` beside the freight driver they name)
  rows whose HINT LINE carried a fenced id  16 of 118

dc18 STAYS AND IT IS NOT A FENCE QUESTION: an open-interest-as-a-market-fact ask answered with
`cot_positioning` + `managed_money_positioning`, and positioning is subject-eligible by D18 and by the
owner's own scenario. Whether the planner should have declined it is a planner judgement the next
billed run measures. AND THE WHOLE TABLE IS A CEILING RATHER THAN A PREDICTION: the picks it removes
are structurally impossible under the fence, but what a planner does with the SHORTER list on those
six rows is what no re-read of banked draws can answer.

(2) THE CARRY RULE. `subject_ambiguous` is stamped only when the candidates at :data:`AMBIG_FLOOR`
came from the SEMANTIC tier -- no T0 or T1 hit on the phrase -- and the planner picked nothing. A free
tier that matched means the planner was shown the driver BY NAME and declined anyway, which is a
decision and not an ambiguity, and dc23 (a how-to-compute ask that names its quantity outright) is
exactly that row. MEASURED on the free layer-1 re-run of deck v2 under this build: 5 of 118 rows carry
at AMBIG_FLOOR raw; the shipped path carries 2, and **0 of the 1 decoy row** -- the L1 FATAL bar's only
row reaches no reader. THE BAR ITSELF IS UNMOVED and still grades the raw count, because retargeting a
pre-registered bar inside the sitting whose change it grades is how an instrument stops being
independent of what it measures; the runner prints BOTH readings and the retarget is docketed.

(3) `ambiguous()` IS GROUP-DEDUPED, which is the second docket above. `crush_margin` 0.7962 and
`crush_margin_expansion` 0.7803 are one driver (`ref:crush_margin_z`), so the render's "either of two
drivers this estate tracks" and the seam's `len(amb) >= 2` now count DRIVERS. The key is stamped onto
:class:`SubjectHints` by :func:`resolve`, because the production caller of `ambiguous()` is the
orchestrator AFTER `plan_turn` and holds no graph.

WHAT THIS COSTS, STATED. The held-out deck carries ONE row whose expected id is `calendar_spread`
(hs_016, synonym). Under the fence that row cannot resolve at layer 2 by construction, so it is a
KNOWN casualty of a deliberate design decision and not a resolver miss -- a desk asking whether the
board is paying anyone to carry it is asking about the curve, and this build's answer is that the
curve is a CONDITION and never a subject. It must be scored as such when the one-shot is spent, not
counted as a synonym failure. No in-tree deck row expects a fenced id (MEASURED on both v1 and v2)."""
