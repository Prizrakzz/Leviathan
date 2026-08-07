"""Response contracts (D-RC Phase B) — the per-question-shape section plans, ONE producer.

A LEAF module by construction: imports NOTHING from leviathan.graphrag (pure data + pure string
functions), so answer.py, eval.py, orchestrator.py, intent.py and config_check.py can all import it
without cycles. This is the structural fix for the estate's duplicate-and-pin idiom (COMPAT-9): a
per-contract table hand-copied into two modules WILL drift; one producer cannot.

NAMING, load-bearing twice over: this module is `response_contracts` because `contracts.py` ALREADY
EXISTS (the pydantic->pyarrow extraction schema; live importers) — and the FIELD is
`response_contract` everywhere because `contract`/`contracts` already mean commodity ids in every
result dict and on session.TurnRecord.

THE SPINE INVARIANT (D-RC-2): every plan OPENS with '## Mechanism', CONTAINS '## What to watch',
and preserves the relative order of whichever of the four canonical headings it carries; plans may
omit only the two headings that are already conditional today. Consequence, by construction:
eval._FIXED_SCAFFOLD / _scaffold_ok / answer._SECTION_KINDS and their parity pins are UNCHANGED,
`mechanism_scaffold_ok` keeps identical semantics on every contract, and `scaffold_violations`
stays a must-be-0 gate. v1 uses ONLY the nine reserved heading literals already in the tree
(D-RC-3): no new heading name, so no register/_sectionize/FE surface moves.

HOW A CONTRACT IS REALIZED (D-RC-1 + D-RC-8): the emit_answer schema and render() are untouched —
section shape is 100% prompt-borne. A non-default contract REWRITES the three places the mentor
persona states the fixed-four mandate (never append-only: an appended directive contradicting the
base mandate is the #1 failure mode). The rewrite is needle-verified: `apply()` asserts each needle
is present before replacing, so persona drift reds a test instead of silently no-opping. The
`default` contract performs ZERO replacements and its directive is the EMPTY STRING — flag-off and
selector-miss turns are byte-identical trivially, not by promise (the fail-open guarantee).

`outlook` is REGISTRY-DESCRIBED but PASSTHROUGH (D-RC-5): the register-affecting outlook gate keeps
sole authority and its persona path (_SYSTEM_OUTLOOK) is already correct; the entry exists so the
selector can stamp it and pins can scope to it, and apply() returns the base unchanged.

COMPOSITION MANDATES (D-CC-1) ride the SAME two seams and add no third one: apply() widens the word
budget, directive() appends the mandate paragraphs. They are driven by a CENSUS dict the caller
computes DETERMINISTICALLY from what the turn actually holds (answer._composition_census) and threads
in as an additive keyword -- `census=None` is byte-identical to the pre-D-CC module on every path, so
the composition lever has its own off state independent of which contract was selected. The three
laws they are built to (from the D-DV-2 judge verdict that named the gaps verbatim): a directive may
only bind to what the turn WAS SHOWN (hence a census, never an LLM roster); every mandate carries an
"or say the record can't" branch as a FIRST-CLASS ending, never a failure mode; and no mandate may
manufacture a number (ordinal-when-thin doctrine).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── the NINE reserved heading literals (D-RC-3: the complete v1 vocabulary; no new names) ────────────
MECHANISM = "## Mechanism"
RECORD = "## The record"
DISAGREES = "## Where the record disagrees"
WATCH = "## What to watch"
EPISODES = "## Episodes"
CROSS = "## Cross-commodity"
COMPLEX = "## Complex-wide move"
HISTORY = "## Recorded history"
OUTLOOK = "## Outlook"
SECTIONS = frozenset({MECHANISM, RECORD, DISAGREES, WATCH, EPISODES, CROSS, COMPLEX, HISTORY, OUTLOOK})

# The four canonical headings whose relative order the spine invariant preserves (== eval._FIXED_SCAFFOLD,
# pinned by a cross-import test, never imported here — leaf module).
CANONICAL = (MECHANISM, RECORD, DISAGREES, WATCH)

DEFAULT = "default"


@dataclass(frozen=True)
class Contract:
    name: str
    sections: tuple                      # ordered plan; conditional headings marked in `conditional`
    conditional: tuple = ()              # subset of sections rendered only when their condition holds
    licenses_episodes: bool = False      # the ONLY v1 authority for '## Episodes' when contracts are ON
    budget: str = "150-220"              # the word-budget phrase substituted into LENGTH DISCIPLINE
    directive: str = ""                  # emphasis paragraph appended LAST ("" = nothing appended)
    passthrough: bool = False            # registry-described only: apply() returns base unchanged


CONTRACTS: dict[str, Contract] = {c.name: c for c in (
    Contract(
        name=DEFAULT,
        sections=(MECHANISM, RECORD, DISAGREES, WATCH),
        conditional=(RECORD, DISAGREES),
        budget="150-220",
        directive="",                    # LOAD-BEARING: the empty string IS the fail-open guarantee
    ),
    Contract(
        name="verification",
        sections=(MECHANISM, RECORD, DISAGREES, WATCH),
        conditional=(DISAGREES,),
        budget="120-200",
        directive=(
            "\n\nVERIFICATION EMPHASIS (this question asserts something and asks whether the record "
            "backs it): open '## Mechanism' with ONE sentence stating the standard you are applying — "
            "documented = a dated cited item inside the asserted window; inferred = the driver model "
            "carries the edge but the record is silent there; contradicted = a cited item points the "
            "other way; not in the record = neither. Then, under '## The record', give a PER-CLAIM "
            "verdict for each distinct claim in the user's premise, each verdict carrying its citation "
            "or naming its absence plainly. Never smooth distinct claims into one verdict."),
    ),
    Contract(
        name="counterfactual",
        sections=(MECHANISM, RECORD, WATCH),
        conditional=(RECORD,),
        budget="150-220",
        directive=(
            "\n\nCOUNTERFACTUAL EMPHASIS (this question poses a hypothetical the record may not "
            "carry): reason ONLY along edges the driver model actually licenses, edge by edge with "
            "sign, confidence and lag, and state EXPLICITLY where the model carries no edge for the "
            "hypothetical — that statement is the product, never a failure. Name the conditions under "
            "which the licensed path turns convex (what has to already be tight). Cited analogue "
            "episodes may ground a hop; never invent a path or a magnitude the model does not carry."),
    ),
    Contract(
        name="enumeration",
        sections=(MECHANISM, RECORD, EPISODES, DISAGREES, WATCH),
        conditional=(DISAGREES,),
        licenses_episodes=True,          # the ONE v1 license for '## Episodes'
        budget="220-320",
        directive=(
            "\n\nENUMERATION EMPHASIS (this question asks for the historical record, occurrence by "
            "occurrence): '## The record' and '## Episodes' carry the answer — one entry per "
            "occurrence, dated, each with its own citation or its absence stated, ordered earliest "
            "first. Do not smooth occurrences into a 'usually'; where two occurrences point opposite "
            "ways, show the fork under '## Where the record disagrees'."),
    ),
    Contract(
        name="ranking",
        sections=(MECHANISM, RECORD, WATCH),
        conditional=(),
        budget="90-160",
        directive=(
            "\n\nRANKING EMPHASIS (this question asks who ranks where): open '## Mechanism' with the "
            "METRIC DECLARATION in one or two sentences — which measure (production vs exports, and "
            "the unit), which marketing year, which source — because 'largest producer' and 'largest "
            "exporter' are different lists. Then '## The record' IS the ranking: observed rows only, "
            "one line per ranked member, value + year + citation. No adjacent-driver padding; if the "
            "data cannot rank (rows missing), say exactly which rows are absent."),
    ),
    Contract(
        name="compare",
        sections=(MECHANISM, RECORD, DISAGREES, WATCH),
        conditional=(DISAGREES,),
        budget="200-300",
        directive=(
            "\n\nCOMPARISON EMPHASIS (this question sets two or more markets side by side): organize "
            "PER AXIS, never per commodity — balance-sheet tightness, dominant driver (sign + "
            "confidence), shared macro exposure, then the cross-commodity linkage itself: name the "
            "actual substitution/transmission channel between the compared markets or state plainly "
            "that the model carries only a narrow one (and which). A comparison that runs one "
            "commodity's story and then the other's is the failure mode; the spread IS the answer."),
    ),
    Contract(
        name="context_node",
        sections=(MECHANISM, WATCH),
        conditional=(),
        budget="60-120",
        directive=(
            "\n\nCONTEXT-NODE EMPHASIS (this question asks about an untracked/linkage commodity): "
            "linkage-first and SHORT — the edge(s) the model carries, each with direction and "
            "confidence, or explicitly declared unsigned where the model names the channel but "
            "assigns no sign. One note that it is not itself a tracked contract. Nothing else; "
            "concision is the contract here."),
    ),
    Contract(
        name="horizon",
        sections=(MECHANISM, RECORD, WATCH),
        conditional=(RECORD,),
        budget="200-300",
        directive=(
            "\n\nHORIZON EMPHASIS (this question asks what to watch across MULTIPLE time horizons): "
            "'## What to watch' IS the answer and is organized as one short block per horizon — "
            "weeks, months, quarters, years (only the horizons the question spans) — each block "
            "naming its trigger or release (scheduled reports and crop-calendar gates for the near "
            "buckets, structural drivers for the far ones) with the cited playbook precedent or its "
            "absence stated plainly. Do not smooth horizons into one undated list; a driver that "
            "matters at every horizon is stated once at the bucket where it BINDS first."),
    ),
    Contract(
        name="recency",
        sections=(MECHANISM, RECORD, WATCH),
        conditional=(),
        budget="120-200",
        directive=(
            "\n\nRECENCY EMPHASIS (this question asks about NOW / a recent window): '## The record' "
            "opens with the record's EDGE — the newest item you hold per source family, dated — and "
            "states plainly where the asked window is NOT covered; the honest gap statement beats a "
            "smoothed answer. Never present-tense an old item; every 'currently' must be backed by "
            "the newest date you actually hold."),
    ),
    Contract(
        name="outlook",
        sections=(MECHANISM, RECORD, DISAGREES, WATCH, OUTLOOK),
        conditional=(RECORD, DISAGREES),
        budget="220-320",
        passthrough=True,                # formalization ONLY: the outlook gate + _SYSTEM_OUTLOOK own this
        directive="",
    ),
)}


# ── the three needles apply() rewrites (D-RC-8: rewrite, never append-contradict) ────────────────────
# Byte-for-byte spans of answer._SYSTEM_MENTOR, pinned by tests/unit/test_response_contracts.py —
# if the persona is ever reworded, the needle test reds and this module is updated DELIBERATELY.
NEEDLE_STRUCTURE = (
    "Structure "
    "the `mechanism` field under these four markdown headings, in this exact order and wording: '## Mechanism', "
    "'## The record', '## Where the record disagrees', '## What to watch'. Always include '## Mechanism' and "
    "'## What to watch'. Include '## The record' whenever you cite any dated or observed evidence. Include "
    "'## Where the record disagrees' ONLY when there is a genuine conflict WITHIN the record -- opposing "
    "same-confidence drivers, sources of different trust tiers that disagree, or members/eras that diverge; "
    "OMIT that heading when there is no disagreement (never write a 'no disagreement' line). This heading is "
    "NEVER for a contradiction between the record and the USER'S PREMISE -- when the record contradicts what "
    "the question assumed, you correct that in the TL;DR (per the premise rule above), never as a fork heading; "
    "the record disagreeing with the reader is not the record disagreeing with itself.")
NEEDLE_BUDGET = "target 150-220 words across the four sections"
NEEDLE_FIELDLIST = "structured under the four '## ' headings above"

_DISAGREES_RULE = (
    "Include '## Where the record disagrees' ONLY when there is a genuine conflict WITHIN the "
    "record -- opposing same-confidence drivers, sources of different trust tiers that disagree, or "
    "members/eras that diverge; OMIT that heading when there is no disagreement (never write a 'no "
    "disagreement' line). This heading is NEVER for a contradiction between the record and the "
    "USER'S PREMISE -- when the record contradicts what the question assumed, you correct that in "
    "the TL;DR (per the premise rule above), never as a fork heading; the record disagreeing with "
    "the reader is not the record disagreeing with itself.")
_RECORD_RULE = "Include '## The record' whenever you cite any dated or observed evidence."
_EPISODES_RULE = (
    "Include '## Episodes' with the injected DATED EPISODES grounded per its own rules, placed "
    "after '## The record' and before '## What to watch'.")


# -- D-CC-1 composition mandates: which contract carries which, and the budget arithmetic ------------
# WHICH CONTRACTS. Cue families, not modes: the mandate's PRESENCE follows the selected contract and
# its STRENGTH follows the census, so a wide turn and a lean turn on the same question get the same
# mandate with different counts. `compare` carries BOTH because its two jobs are exactly the two gaps
# -- it ranks the compared markets (rank-complete) and its own directive is the mechanism-of-linkage
# directive ("name the actual substitution/transmission channel"), which is where a convexity point
# lives (threshold-locate).
#
# THE MECHANISM-CUE HOLE, RECORDED RATHER THAN PAPERED OVER: the v1 menu has no `mechanism` contract,
# and the two D-DV-2 width rows that produced the "never locates the convexity threshold" verdict
# (dv_sub_ddg_floor, dv_chain_nitrogen_acres) both select NOTHING -- they run on `default`, whose
# directive is the empty string by the D-RC-1 fail-open law. threshold-locate therefore CANNOT reach
# them without a selector change, which is a separate decision (the selector is unchanged this wave).
RANK_COMPLETE = frozenset({"ranking", "compare"})
THRESHOLD_LOCATE = frozenset({"counterfactual", "compare"})
# episode-coverage needs no set: it rides `licenses_episodes`, so the contract that owns the
# '## Episodes' surface is the contract that owns the mandate to fill it -- one authority, not two.

MIN_RANK_ENTITIES = 2          # a one-name roster is not a list; below this the mandate says nothing
MAX_NAMED_ENTITIES = 12        # names spelled INTO the directive; the true count is always stated
# Budget arithmetic, stated so it can be argued with. A ranked line ("Russia -- export tax raised
# 2024-09-01, high odds [E4]") runs ~14 words. Every contract that carries rank-complete already
# budgets a few ranked lines, so the first MIN_RANK_ENTITIES+1 are FREE and only the excess buys
# words: extra = min(160, 14 * max(0, n - 3)). The +160 cap is deliberate and binds from n = 15 -- past
# that the answer is a table, and a budget that grows without bound is how a mandate turns into a
# strip-rate regression (D-CC-3 R1: contracts do no harm).
BUDGET_FREE_ENTITIES = 3
BUDGET_WORDS_PER_ENTITY = 14
BUDGET_MAX_EXTRA = 160


def _roster(census: dict | None) -> tuple[tuple[str, ...], int]:
    """(names to spell out, TRUE distinct count) from a census dict; ((), 0) for None/malformed.

    FAIL-OPEN like every other read in this module: a census the caller built wrong yields no mandate
    rather than a broken one. The count is the census's own `n_entities` when present -- the roster
    may be capped upstream and the STATED count must be the truth, never the length of what fit."""
    if not isinstance(census, dict):
        return (), 0
    ents = tuple(str(e) for e in (census.get("entities") or ()) if str(e).strip())
    try:
        n = int(census.get("n_entities", len(ents)))
    except (TypeError, ValueError):
        n = len(ents)
    return ents, max(n, len(ents))


def _census_int(census: dict | None, key: str) -> int:
    if not isinstance(census, dict):
        return 0
    try:
        return max(0, int(census.get(key) or 0))
    except (TypeError, ValueError):
        return 0


def _rank_roster(name: str | None, census: dict | None) -> tuple[tuple[str, ...], int] | None:
    """The ONE predicate for "does rank-complete fire on this turn", shared by the budget widening in
    apply() and the directive text in composition(). Two derivations of one condition is how a budget
    and the mandate it exists to pay for drift apart."""
    if name not in RANK_COMPLETE:
        return None
    ents, n = _roster(census)
    return (ents, n) if n >= MIN_RANK_ENTITIES else None


def widen_budget(budget: str, n_entities: int) -> str:
    """The rank-complete word-budget widening (arithmetic documented above). Returns `budget`
    UNCHANGED for anything that is not the `lo-hi` shape -- the reasoning_modes.scale_budget
    fail-open, re-spelled here rather than imported because both modules are leaves and neither may
    import the other (the D-AM-10 note on _mode_budget)."""
    extra = min(BUDGET_MAX_EXTRA, BUDGET_WORDS_PER_ENTITY * max(0, n_entities - BUDGET_FREE_ENTITIES))
    parts = str(budget or "").split("-")
    if extra <= 0 or len(parts) != 2:
        return budget
    try:
        lo, hi = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return budget
    return f"{lo + extra}-{hi + extra}"


def rank_complete_clause(names: tuple, n: int) -> str:
    """Gap 1, verbatim from the judge: "never delivers the FULL ranked list"."""
    shown = list(names)[:MAX_NAMED_ENTITIES]
    tail = (f", and {n - len(shown)} more named in the evidence above" if n > len(shown) else "")
    return ("\n\nRANK-COMPLETE (this turn's own census, not a general instruction): the assembled "
            f"evidence carries {n} candidate names -- {', '.join(shown)}{tail}. Cover EVERY one that "
            "belongs to the list this question asks for: one line each, carrying its number or its "
            "odds, ordered. A candidate you cannot place is NAMED anyway, on its own line, with the "
            "reason stated -- 'no dated row at the as-of' is the standard reason and is a COMPLETE "
            "line, not an apology. A name that is not a member of the asked-for list (a tracked "
            "contract id where the question ranks origins, say) is left out silently. Never extend "
            "the list with a name the evidence does not carry.")


def threshold_locate_clause(n_evidence: int) -> str:
    """Gap 2: "never locates the convexity threshold". Two endings, both first-class."""
    held = (f"the {n_evidence} evidence item(s) and number row(s) this turn holds"
            if n_evidence else "the record you were shown")
    return ("\n\nTHRESHOLD-LOCATE: say WHERE the relationship stops being proportional -- the level, "
            "ratio or spread at which the response changes character -- and back that point with a "
            f"handle from {held}. If the record does not locate one, say exactly that ('the record "
            "does not locate a switch point here') and name what would locate it (which series, "
            "which observation). Those are the ONLY two endings. A threshold you cannot back is a "
            "fabrication; an answer that never reaches the question is a miss.")


def episode_coverage_clause(n_windows: int) -> str:
    """Gap 3: "fails to enumerate the dated episodes shown"."""
    return (f"\n\nEPISODE-COVERAGE: {n_windows} dated episode window(s) were injected into this "
            "prompt. Enumerate every one -- one entry per window, each carrying its own dates -- or, "
            "for any window you leave out, say WHICH window and why ('no citable item inside that "
            "window'). The silent omission is the failure; the declared one is an honest answer.")


def composition(name: str | None, census: dict | None = None) -> str:
    """The census-driven mandate paragraphs for this contract ('' whenever nothing fires).

    Appended AFTER the contract's own directive by the caller, so the mandates read as the specific
    obligations of a shape the directive has already described. '' for None/default/passthrough/
    unknown and for census=None, which is what makes the composition lever independently reversible:
    the same image serves the D-CC-3 arms and the pre-D-CC bytes on one env flip."""
    if census is None or not name or name == DEFAULT:
        return ""
    c = CONTRACTS.get(name)
    if c is None or c.passthrough:
        return ""
    out = []
    rank = _rank_roster(name, census)
    if rank:
        out.append(rank_complete_clause(*rank))
    if name in THRESHOLD_LOCATE:
        out.append(threshold_locate_clause(_census_int(census, "n_evidence")))
    n_win = _census_int(census, "n_episode_windows")
    if c.licenses_episodes and n_win > 0:
        out.append(episode_coverage_clause(n_win))
    return "".join(out)


def structure_clause(name: str) -> str:
    """The contract-rendered replacement for NEEDLE_STRUCTURE: the SAME sentence shape, listing this
    contract's plan. Always-include = the non-conditional sections; each conditional section keeps
    its existing inclusion rule verbatim (the rules are the mentor's own bytes, factored)."""
    c = CONTRACTS[name]
    quoted = ", ".join(f"'{s}'" for s in c.sections)
    always = [s for s in c.sections if s not in c.conditional]
    parts = [f"Structure the `mechanism` field under these markdown headings, in this exact order "
             f"and wording: {quoted}. Always include " + " and ".join(f"'{s}'" for s in always) + "."]
    if RECORD in c.conditional:
        parts.append(_RECORD_RULE)
    if EPISODES in c.sections:
        parts.append(_EPISODES_RULE)
    if DISAGREES in c.sections:
        parts.append(_DISAGREES_RULE)
    return " ".join(parts)


def apply(base: str, name: str | None, *, budget: str | None = None,
          census: dict | None = None) -> str:
    """Rewrite the persona's three mandate sites for this contract; the base string UNCHANGED for
    None / default / passthrough / unknown (fail-open). Needle presence is asserted — a reworded
    persona must red loudly (test-pinned), never silently stop rewriting.

    `budget` (D-AM-10) OVERRIDES this contract's word range for this turn only — the reasoning-mode
    length lever. It is a pre-computed phrase, not a factor, so this module stays ignorant of modes
    (both are leaves and neither may import the other). None = the contract's own budget, which is
    the flag-off/standard path and therefore byte-identical.

    `census` (D-CC-1) widens that range when rank-complete fires, because the mandate buys LINES and
    a mandate the budget will not pay for is a mandate that loses. ORDER, stated because it is
    compounding: the mode scales the range FIRST (answer._mode_budget hands the scaled phrase in),
    the census widens SECOND -- multiplicative then additive. None = untouched = byte-identical."""
    if not name or name == DEFAULT:
        return base
    c = CONTRACTS.get(name)
    if c is None or c.passthrough:
        return base
    for needle in (NEEDLE_STRUCTURE, NEEDLE_BUDGET, NEEDLE_FIELDLIST):
        assert needle in base, f"persona needle missing for response contract rewrite: {needle[:60]}..."
    n_sec = len(c.sections)
    _budget = budget or c.budget
    rank = _rank_roster(name, census) if census is not None else None
    if rank:
        _budget = widen_budget(_budget, rank[1])
    return (base
            .replace(NEEDLE_STRUCTURE, structure_clause(name))
            .replace(NEEDLE_BUDGET, f"target {_budget} words across the {n_sec} sections")
            .replace(NEEDLE_FIELDLIST, "structured under the '## ' headings above"))


def directive(name: str | None, *, census: dict | None = None) -> str:
    """The emphasis paragraph appended LAST to the persona ('' for None/default/unknown/passthrough),
    followed by this turn's composition mandates ('' unless a census is threaded in -- D-CC-1)."""
    c = CONTRACTS.get(name or DEFAULT)
    return (c.directive if c else "") + composition(name, census)


def licenses_episodes(name: str | None) -> bool:
    """Whether this contract licenses the '## Episodes' surface. When contracts are ACTIVE this is
    the ONE authority (the D-RC-11 interim lexical gate stands down for the turn); when contracts
    are off the caller must not consult it."""
    c = CONTRACTS.get(name or DEFAULT)
    return bool(c and c.licenses_episodes)


def valid_names() -> frozenset:
    return frozenset(CONTRACTS)


def spine_ok(name: str) -> bool:
    """The D-RC-2 invariant, checkable per entry (config_check + tests iterate the menu)."""
    c = CONTRACTS[name]
    if not c.sections or c.sections[0] != MECHANISM or WATCH not in c.sections:
        return False
    canon = [s for s in c.sections if s in CANONICAL]
    return canon == [s for s in CANONICAL if s in canon] and set(c.sections) <= SECTIONS


# == D-DR-1: the DOSSIER contract -- ONE document composed from sub-answer NOTES =======================
# DELIBERATELY NOT AN ENTRY IN `CONTRACTS`, and that is a design decision, not an omission:
#   * `valid_names()` IS the turn-path allowlist -- answer._response_contracts_enabled() returns exactly
#     it under GRAPHRAG_RESPONSE_CONTRACT=on (test-pinned) -- so a `dossier` entry would become
#     selectable by intent.select_response_contract on an ordinary desk turn and would be swept live by
#     the wildcard flag value. A document contract must never be reachable from a single turn.
#   * `spine_ok()` is iterated over the whole menu and requires `set(sections) <= SECTIONS`; a dossier
#     carries CANNOT, a heading the nine-literal turn vocabulary (D-RC-3) deliberately does not have.
#     Adding it to SECTIONS would move eval._FIXED_SCAFFOLD's neighbourhood and answer._SECTION_KINDS.
# A dossier is not a turn: it never rides render(), _sectionize, the fixed-four scaffold pins or the
# strips-per-handle deck. So the SHAPE lives here (one producer for the section names, the budget and
# the directive -- the leaf law) and stays off the turn menu by construction.
#
# WHY THE TWO EXTRA MANDATED SECTIONS. D-DR-1 names them: "a 'where the record disagrees' section, an
# explicit 'what the record cannot answer' section". At document scale both are UNCONDITIONAL, which
# INVERTS the turn-path rule that omits DISAGREES when nothing conflicts (_DISAGREES_RULE: "never write
# a 'no disagreement' line"). The inversion is deliberate and is the product: a dossier holds 5-12
# independently-grounded sub-answers, so whether they agree is itself a finding, and the honest branch
# is "these sub-answers do not conflict; here is what they jointly support", never silence. The
# cannot-answer section is the refusal-honest doctrine given its own surface -- a failed or thin
# sub-query must land on the page as a declared gap (D-DR-1's honest-partial law), never be smoothed.
CANNOT = "## What the record cannot answer"

DOSSIER_SECTIONS: tuple = (MECHANISM, RECORD, EPISODES, CROSS, DISAGREES, CANNOT, WATCH)

DOSSIER = Contract(
    name="dossier",
    sections=DOSSIER_SECTIONS,
    conditional=(),                      # every section is MANDATED at document scale (see above)
    licenses_episodes=True,              # the dossier owns its own '## Episodes' surface
    budget="900-1500",
    directive=(
        "\n\nDOSSIER COMPOSITION (this is a DOCUMENT assembled from the NOTES of several separately "
        "grounded sub-answers, not a single turn): you are given, per sub-question, its own claims and "
        "its own citation pairs. Compose ONE document. Every section is REQUIRED, including the two "
        "that a single answer may omit:\n"
        "- '## Where the record disagrees' is required even when nothing conflicts -- then say so "
        "plainly and name what the sub-answers jointly support instead. Where they DO conflict, name "
        "both sides, cite both, and say which is better backed and why (vintage, source tier, "
        "coverage), or that the record does not settle it.\n"
        "- '## What the record cannot answer' is required always: every sub-question that failed, "
        "returned nothing citable, or was answered only in part goes here BY NAME with the reason. A "
        "gap you declare is a finding; a gap you paper over is the failure.\n"
        "CITATIONS: use ONLY the handles listed in the NOTES, exactly as written. Never mint a handle, "
        "never renumber one, never carry a number that no listed pair backs. A claim you cannot pin to "
        "a listed pair does not go in the document.\n"
        "Do not restate the sub-answers one after another -- that is the failure mode. Organize by "
        "FINDING; a finding that several sub-questions reached independently is stated once and carries "
        "each of its handles."),
)


def dossier_budget(census: dict | None = None) -> str:
    """The document word budget, widened by the union roster exactly as `apply()` widens a turn's --
    same arithmetic, same reason (the mandate buys LINES and an unpaid mandate loses)."""
    ents, n = _roster(census)
    return widen_budget(DOSSIER.budget, n) if n >= MIN_RANK_ENTITIES else DOSSIER.budget


def dossier_directive(census: dict | None = None) -> str:
    """DOSSIER.directive + this document's composition mandates ('' census -> base directive only).

    The mandates are the SAME three clause producers the turn path uses (`rank_complete_clause`,
    `threshold_locate_clause`, `episode_coverage_clause`) -- one producer, so a mandate cannot mean one
    thing on a turn and another on a document. What changes is the CENSUS they bind to: at synthesis it
    is the UNION over every sub-answer's notes, which is width by construction. That is the D-CC-3 R1
    consequence honored: mandates are affordable exactly where width already exists, and the dossier
    synthesis is the widest surface in the estate.

    threshold-locate is unconditional here (it needs no roster and has an explicit "the record does not
    locate one" ending); rank-complete needs >= MIN_RANK_ENTITIES names; episode-coverage needs windows."""
    if census is None:
        return DOSSIER.directive
    out = [DOSSIER.directive]
    ents, n = _roster(census)
    if n >= MIN_RANK_ENTITIES:
        out.append(rank_complete_clause(ents, n))
    out.append(threshold_locate_clause(_census_int(census, "n_evidence")))
    n_win = _census_int(census, "n_episode_windows")
    if n_win > 0:
        out.append(episode_coverage_clause(n_win))
    return "".join(out)


def dossier_structure_clause() -> str:
    """The section plan as one imperative sentence (the `structure_clause` shape, for a prompt that has
    no mentor persona to rewrite -- the dossier system prompt is built, not needled)."""
    quoted = ", ".join(f"'{s}'" for s in DOSSIER_SECTIONS)
    return (f"Structure the `mechanism` field under these markdown headings, in this exact order and "
            f"wording: {quoted}. Include EVERY one of them.")
