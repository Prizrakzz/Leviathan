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


def apply(base: str, name: str | None) -> str:
    """Rewrite the persona's three mandate sites for this contract; the base string UNCHANGED for
    None / default / passthrough / unknown (fail-open). Needle presence is asserted — a reworded
    persona must red loudly (test-pinned), never silently stop rewriting."""
    if not name or name == DEFAULT:
        return base
    c = CONTRACTS.get(name)
    if c is None or c.passthrough:
        return base
    for needle in (NEEDLE_STRUCTURE, NEEDLE_BUDGET, NEEDLE_FIELDLIST):
        assert needle in base, f"persona needle missing for response contract rewrite: {needle[:60]}..."
    n_sec = len(c.sections)
    return (base
            .replace(NEEDLE_STRUCTURE, structure_clause(name))
            .replace(NEEDLE_BUDGET, f"target {c.budget} words across the {n_sec} sections")
            .replace(NEEDLE_FIELDLIST, "structured under the '## ' headings above"))


def directive(name: str | None) -> str:
    """The emphasis paragraph appended LAST to the persona ('' for None/default/unknown/passthrough)."""
    c = CONTRACTS.get(name or DEFAULT)
    return c.directive if c else ""


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
