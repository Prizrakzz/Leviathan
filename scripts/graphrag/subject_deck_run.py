"""THE SUBJECT-RESOLVER DECK RUNNER -- D9's two layers and D10's latency bar, one instrument.

Design: docs/private/SUBJECT_RESOLVER_SITTING_2026-09-09.md (D9 the deck and the pre-registered bars,
D10 the latency budget, D11 phase B's scope). Phase A is commit 69b95316; this is phase B's measurer.

THE SHAPE IS `scripts/xc_planner_soak.py`'s, deliberately and to the letter: pre-registered bars graded
IN CODE, a `--dry-run` that prints the exact call plan and the dollar estimate BEFORE anything is spent,
a verdict vocabulary of {LAND-DARK, STOP} that this script cannot widen, ASCII-only stdout, and an
artifact written for offline re-audit. What it adds is a FREE layer and a FREE latency harness, so most
of what it measures costs nothing at all.

  --layer 1      THE DETERMINISTIC TIERS. `subject.exact_ids` + `alias_ids` + `semantic_candidates` on
                 the real vocabulary artifact. No LLM, no network, no spend. This is the instrument
                 that was frozen in phase A, re-run here against whatever deck is handed to it.
  --layer 2      THE PLANNER. `dispatch.plan_turn` with the resolver's two kwargs threaded -- the same
                 wiring `orchestrator.py` does under GRAPHRAG_SUBJECT_RESOLVER -- at the pinned seat
                 (claude-sonnet-4-6, temperature 0 through `dispatch._temp_kw`, `max_contracts` at the
                 deck's own tier). `--draws 3`, a row passes at >= 2 of 3. THIS is the billed half.
  --latency      D10. The ADDED WALL PER TURN, flag off against flag on, over the deck's own phrases.
                 Free.

WHAT LAYER 2 IS FOR, said plainly. Layer 1 measures whether the tiers put the right driver in front of
the planner. It cannot measure what the planner DOES with the list, and the phase-A bank names the open
risk in terms: 12 of 18 held-out decoy rows still put a candidate above CAND_FLOOR in front of the
planner (zero above AMBIG_FLOOR, so the carry is clean). A decoy the PLANNER picks is a board anchored
on a question that named no driver, and that is the one failure this layer exists to price. It is a
FATAL bar, not a rate.

THE D10 MEASUREMENT, AND WHY IT IS A DIFFERENCE AND NOT A DURATION. `resolve()` runs BEFORE
`plan_turn`, so on the first call of a turn `evidence._Q_CACHE` is COLD and the resolver -- not the
walk -- is the caller that fills it (phase A addendum A1, measured p50 351 / p90 387 ms). But the walk
re-embeds the SAME verbatim query one call later and hits the memo the resolver just filled, measured
at 0.007 ms. So the resolver's own wall is mostly a cost the turn was going to pay anyway, and D10's
budget -- "<= 150 ms ADDED per turn, flag on, p90" -- is stated over the difference. Both figures are
banked: `ms_board_subject_ms` is the counter production will see (the resolver's own wall, cold), and
`added_wall_per_turn_ms` is what the flag actually costs a walking lane and what the bar is graded on.
`config_check.check_subject_resolver` clause (13) reads the newest bank and reds above the budget.

NO HELD-OUT PHRASE IS EVER WRITTEN INTO THE TREE. The scratchpad artifact carries per-row detail; the
in-tree bank under `data/subject_resolver/<date>/` carries CLASS-LEVEL COUNTS AND NOTHING ELSE -- no
phrase, no row id, no expected id. The `test_p65`-style absence pin in `tests/unit/test_subject_
resolver.py` stays green by construction.

AND WHAT IS DURABLE WHERE, because the scratchpad is session-temp and the one-shot happens once.
THREE homes, and they do not overlap: the TRACKED bank keeps the phrase-free, id-free record and its
index (it is the certificate, and it is committed); the SCRATCHPAD keeps the full artifact for the
session; and `--full-artifact-dir` copies that full artifact to an UNTRACKED durable home,
`docs/private/subject_heldout/`, which is gitignored in this tree and is where the held-out deck
itself lives. A `--full-artifact-dir` inside this repo that `git check-ignore` does not call ignored
is REFUSED before the run reads anything.

THE ARTIFACT IS ID-KEYED AND CARRIES NO ASK -- measured, and said here because "the full artifact"
does not sound like it. `layer1_rows` and `layer2_rows` carry `id`, `klass`, `expect`, the hint
counts and every draw's picks; neither carries the deck's `phrase`. So a durable copy is COMPLETE
only beside the deck that keys it, which is why the deck and the copies share one untracked home: the
deck is the id -> ask join, and nothing else in the estate holds it.

THE CURRENT CALIBRATION DECK IS `configs/graphrag/subject_deck_v3.yaml` and `--deck` has NO DEFAULT
by design: the deck is the instrument, a billed run on the wrong one is money spent measuring nothing,
and a default is exactly how the wrong one gets measured. v1 and v2 are FROZEN PREDECESSORS -- they
still run, and they still reproduce their own banked figures, but the deck phase E grades is v3 (v2's
118 rows with dc18 re-labelled from decoy to alias, so 27 decoys and 91 non-decoy rows).

USAGE (the owner's shell is Windows PowerShell 5.1: chain with `;`, never `&&`)
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck configs/graphrag/subject_deck_v3.yaml --layer both --dry-run
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck configs/graphrag/subject_deck_v3.yaml --layer 1
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck configs/graphrag/subject_deck_v3.yaml --latency
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck configs/graphrag/subject_deck_v3.yaml --layer 2 --cap-usd 4
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --deck <heldout> --layer 2 --cap-usd 4 --full-artifact-dir docs/private/subject_heldout
  $env:PYTHONPATH="src"; python scripts/graphrag/subject_deck_run.py --grade-record data/subject_resolver/<date>/<deck>_layer2_<stamp>.json

THE INSTRUMENT IS FENCED BEFORE THE MEASUREMENT IS. `artifact: ok` grades THE FILE; the embedder is a
different failure, and when it dies `semantic_candidates` returns `unreadable` with zero candidates on
every phrase while `load_vocab` in the same process still says `ok`. That state scores, verdicts and
banks a VACUOUS run with every class at its lexical floor -- and at layer 2 it BILLS a planner call per
draw on a hint line that is the empty string. So the per-row `vocab_status` census is read after layer
1 and a single decline REFUSES the run: nothing is banked, nothing is spent, and a diagnostic marked
NON-CERTIFYING is written to the scratchpad instead. See :func:`instrument_census`.

ANTHROPIC_API_KEY is read from the environment and NEVER printed, logged or written to an artifact.
Exit codes: 0 = ran, every evaluated bar PASS (verdict LAND-DARK); 1 = a bar STOPped; 2 = refused
before spending (a missing deck, a bad flag, no key, a stale artifact, or a DEAD INSTRUMENT).

THE EXIT CODE IS NOT THE HELD-OUT GATE, and reading it as one is the likeliest operator error on the
billed run. The exit code grades EVERY evaluated bar on the run TOGETHER, layer 1's included -- and
the calibration decks carry a layer-1 decoy carry (dc23) that is FATAL, pre-existing, measured, and
authorised to be read past by the deck's own header, which states that the block is graded on the
LAYER-2 bar independent of that carry. So a v3 run whose layer-2 gate passes in full still exits 1.
:func:`oneshot_gate` therefore grades the pre-registered gate IN CODE, as FOURTEEN checks -- TWO over
the ARTIFACT it was handed (its CLASS, and that its FILE NAME ENDS in the stamp of the run inside it
-- a SUFFIX test; identity is bound by the DECK's rows digest, never by a name),
SEVEN over the layer-2 fields the bars are stated over
(`layer2.per_class.decoy.{n,scored,fired}`, `layer2.all_non_decoy.{scored,passed}`,
`layer2.errored_calls`, `layer2.seat_pin.verdict`, `layer2.aborted_on_cost`, and the record's own
class census, with both denominators read from the CERTIFYING DECK FILE rather than from the record)
and FIVE over what actually ran (`planner_block_sha256` against this tree's live pin,
`deck_rows_sha256` against the certifying deck's, `graph_hash` against the graph this tree loads
today, `draws` / `rows_total` / `layer2.calls` against the pre-registered three-draw shape, and
`rescored_from` absent because the gate is stated over a RUN and not over a re-read of one) -- prints
it under its own heading, and banks it INSIDE the per-run record it was computed on. Read THAT -- on
the console, in the artifact JSON, or on the face of the markdown report.

AND `planner_block_sha256` IS A MEASUREMENT AND NOT A DECLARATION, which is the one thing it was not.
`main` used to write the module CONSTANT onto the record while :func:`live_block_sha` read the SAME
constant back, so the PROVENANCE check compared a constant to itself at both ends and nothing in this
runner ever hashed the text the run actually sends. MEASURED free and in-process: with
`dispatch._subject_block` returning a text hashing to 14703c0a77c8 while the pin stayed d7ed2de860fc,
the run RECORDED d7ed2de860fc, the readout printed `PASS  PROVENANCE ... d7ed2de860fc against the live
d7ed2de860fc`, and the gate read OPEN with zero failing checks on 354 clean calls. `main` now RENDERS
the block over this run's own `live_ids(graph)`, hashes it, REFUSES before any spend when it is not the
pin, and records the measured digest; the pin stays the comparand the gate grades a LATER reading of
that record against.

WHAT THE GATE IS HANDED, AND WHY THAT IS ITSELF A CHECK. A layer-2 run writes ONE IMMUTABLE PER-RUN
RECORD, `data/subject_resolver/<date>/<deck>_layer2_<generated_utc>.json`, which carries the run's
PROVENANCE, its layer-2 measurement, its bars and the gate verdict computed over THAT SAME document,
is written once, and is never merged into (:func:`layer2_record`, :func:`write_layer2_record`). The
dated `<deck>_summary.json` beside it is a FIXED path that IS merged, and it keeps only a POINTER list
`layer2_runs` plus the latest verdict copied for a human reader (each pointer carries `record_sha256`,
the digest of the record's bytes at the moment the pointer was written -- `--grade-record` puts a
record back against it and REFUSES a mismatch, which is the only way to see a record edited IN PLACE
at its own name; it corroborates and can never open a held gate) -- because a merge whose later run
overwrites the earlier one's provenance while preserving its layer 2 transplants a live block sha and
a live graph hash onto a measurement made under neither (MEASURED on a doctored bank, 2026-09-11: one
free `--layer 1` re-run did exactly that). So the gate reads provenance from INSIDE the layer-2 record
and refuses any other artifact class, the merged summary included.

WHY THE LAST FIVE EXIST. A gate over outcomes alone certifies that SOMETHING was measured cleanly and
not that THIS was: a clean run on deck v2, or one whose draws were made under the block's v2 text, or
one made against a graph this tree no longer loads, or a `--draws 1` run with no 2-of-3 reading in it
at all, or a `--rescore` of a banked run under today's scorer, satisfied all six and opened the gate
on figures the v3 block was never measured by. THE THREE INPUTS ARE INDEPENDENT: the prompt is
substitution-free, so its sha names the text and carries none of the enum; the enum is
`live_ids(graph)`, which is `all_ids(graph)` MINUS the own-structure fence, so `graph_hash` names the
graph half and the fence (a module constant, recorded on every record as `own_structure_fence` beside
`live_ids_count`) names the other; and the asks are the DECK's. Each provenance check is fail-closed
on an ABSENT field, so a bank written before they existed holds the one-shot rather than opening it.

AND WHAT IS RECORDED BUT NOT GRADED, said because a field inside a certificate reads as a graded field
unless it is named otherwise. `runner_sha256` (this file's own bytes) and `runner_git_sha` (the tree's
HEAD, when git answers) ride every record's provenance and are NOT among the fourteen checks: they say
WHICH CODE produced a measurement, for a reader months later, and pinning them would make every later
fix to this script un-gradeable against banks it did not write. `deck_version` and `deck_sha256` are
the same -- recorded; the graded deck identity is the ROWS digest.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:                    # direct `python scripts/graphrag/...`
    sys.path.insert(0, str(_REPO / "src"))

import yaml  # noqa: E402

# ── the pinned seat (D9 layer 2) ─────────────────────────────────────────────────────────────────
# The SAME seat the xc soak pins and for the same reason: the treatment here is a PROMPT SECTION plus
# a schema enum, so a seat that moves would move with it and nothing would be attributable.
SEAT = "claude-sonnet-4-6"
TEMPERATURE = 0
DEFAULT_MAX_CONTRACTS = 2                                 # dispatch.MAX_CONTRACTS, the shipped tier
PER_CALL_USD = 0.01                                       # the planner's per-call anchor (xc round 3)
HARD_CAP_USD = 12.0                                       # the sitting's stated ceiling
DEFAULT_TODAY = "2026-09-10"

# ── WHAT THE ONE-SHOT GATE IS PRE-REGISTERED OVER ────────────────────────────────────────────────
# The gate does not grade "a run"; it grades THE CALIBRATION RUN -- deck v3, three draws on every row,
# under the block v3 pinned in `state.subject`. Those three are the run's IDENTITY, and until they were
# named here the gate read only OUTCOMES: a clean run on deck v2 (28 decoys, 90 non-decoy, internally
# consistent counts) opened it, and so did a run whose draws were made under the block's v2 text, whose
# decoy figures the deck header says in as many words do not carry across. A pre-registered gate whose
# preconditions live in prose is a watched gate; these three constants are what make it a fenced one.
#: The deck the gate certifies -- a LABEL for the readout. The identity it is graded on is the digest
#: below, because `--rescore` decorates the name and a copy under another filename is the same deck.
CERTIFYING_DECK = "subject_deck_v3.yaml"
#: `deck_identity(...)["deck_rows_sha256"]` of `configs/graphrag/subject_deck_v3.yaml` -- the 118 rows
#: in deck order with `max_contracts` 2 and `today` 2026-09-10. PINNED, and `pe9` grades the pin
#: against the live file in both directions: it IS v3's and it is NOT v2's (the two decks differ by one
#: row, which is exactly the collision a name check would have missed).
CERTIFYING_DECK_ROWS_SHA256 = "7b079452fa9652362bcebdeba7441f298642dbfe889399d27c59cdf355ca1c86"
#: The draw count every layer-2 bar on that deck is stated over ("a row passes at >= 2 of 3 draws", and
#: the decoy bar "ZERO picks on ANY draw"). A `--draws 1` run satisfies neither reading and until this
#: was graded it passed the gate: one draw per row, no disagreement possible, every count internally
#: consistent, and the 2-of-3 bar measured by nothing.
CERTIFYING_DRAWS = 3

#: THE ARTIFACT CLASS THE GATE CERTIFIES, written into every per-run layer-2 record and read back by
#: the gate's first check. A gate is a statement about ONE run, and the two in-tree artifacts a run
#: touches are not interchangeable: the per-run record is immutable and carries its provenance beside
#: the measurement that provenance describes; the dated summary is a FIXED path that merges, so its
#: top-level fields name the LATEST run on that deck and date and not the layer 2 underneath them.
#: A version suffix rides the string because a record shape that changes must not be certifiable by a
#: gate written for the old one.
RECORD_KIND = "subject_resolver_layer2_run_v1"
#: The merged summary's own class word, so the gate can REFUSE it by name rather than by inference.
SUMMARY_KIND = "subject_resolver_deck_summary_v1"

SCRATCH = Path("C:/Users/User/AppData/Local/Temp/claude/"
               "C--Users-User-Desktop-Leviathan/360a169c-9409-4bdb-af00-a02392ed35a2/scratchpad/"
               "subject_run")
BANK = _REPO / "data" / "subject_resolver"

#: D9's LAYER-1 bars, by class. `exact` and `alias` are stated over the FREE tiers (T0/T1), every other
#: class over the top-5 candidate list or the union of all three tiers -- the deck header states which.
L1_BARS = {"exact": 1.00, "alias": 1.00, "synonym": 0.90, "misspelling": 0.85,
           "description": 0.75, "acronym": 1.00}
#: D9's LAYER-2 bars, quoted from the spec. `near_duplicate` and `multi` are GROUP bars, not id bars.
L2_BARS = {"synonym": 0.90, "misspelling": 0.85, "description": 0.70,
           "near_duplicate": 1.00, "multi": 1.00}
#: HOW MANY SEPARATE CAUSES A `multi` ROW NAMES -- the class's own contract, quoted from the deck that
#: declares it: "MULTI -- the owner's 'multiple named drivers -> a list, and the boards union'. Two
#: SEPARATE groups, not two names for one thing (that is near_duplicate, one subject)." The count is a
#: CONSTANT here and not a count of the expect list, because the expect list is a list of ALTERNATIVES
#: (:func:`score_layer2`) and its length says nothing about how many causes the ask names: `mu02` lists
#: three ids for two causes. A deck may override it per row with a `concepts:` key -- a list of the
#: alternative-sets, one per cause. v1 and v2 carry none, so every `multi` row on them is scored at
#: two; v3 carries exactly ONE, on `dc18`, and it is not a `multi` row at all: the owner's 2026-09-11
#: ruling re-labelled that row out of the decoy class into `alias`, and the key DECLARES that its five
#: positioning ids are five spellings of ONE cause. On an id class the count is not what the pass rule
#: reads (any pick reaching an expected id or its group passes), so the declaration is there to be
#: read -- by :func:`concept_count`, by the per-row record and by a reader -- rather than to be
#: inferred from a class rule written for a different question.
#: THE LIMITATION IS STATED RATHER THAN HIDDEN: a `multi` row that named THREE causes would be scored
#: against two here and would pass one cause short. Every scored row's `expected_groups` and
#: `groups_reached` ride the per-row record, so the reading is auditable off the bank without a re-run.
MULTI_MIN_CONCEPTS = 2
#: The like-for-like lexical baseline, MEASURED in the recon over its own thirty phrases and reproduced
#: to the row by phase A. Printed beside every result table so the uplift is never quoted from memory.
LEXICAL_BASELINE = {"any_hit_pct": 30.0, "hit_at_1_pct": 23.3,
                    "note": "the shipped driver matcher over the recon's 30 synonym/misspelling/"
                            "description phrases (BRIEF.md sec 6; reproduced 2026-09-10)"}

CLASSES = ("exact", "alias", "synonym", "misspelling", "description", "acronym",
           "near_duplicate", "multi", "decoy")


def _ascii(s) -> str:
    """The owner's console is cp1252: stdout stays ASCII-only (UTF-8 files are fine)."""
    return str(s).encode("ascii", "replace").decode()


def _utc_stamp() -> str:
    """THE RUN'S OWN UTC STAMP, from ONE producer. It is the run's `generated_utc`, the name of its
    scratchpad artifact and the name of its immutable per-run record -- three places that must agree,
    because the record's path is what an operator hands on and the artifact is what he reads it
    against. One second's resolution is deliberate: two layer-2 runs of one deck inside one second
    collide, and a collision is REFUSED rather than resolved (:func:`write_layer2_record`)."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pct(a: int, b: int) -> float:
    return (100.0 * a / b) if b else 0.0


def _pctile(xs: list, q: float) -> float:
    """The p-th percentile, nearest-rank, on a sorted copy. `statistics.quantiles` needs n >= 2 and
    interpolates; nearest-rank is what every other latency bank in this estate reports."""
    if not xs:
        return 0.0
    s = sorted(float(x) for x in xs)
    i = max(0, min(len(s) - 1, int(round(q * len(s) + 0.5)) - 1))
    return s[i]


# ── the deck ─────────────────────────────────────────────────────────────────────────────────────
def load_deck(path: Path) -> dict:
    """Both deck shapes parse the same way: a `rows` list of {id, klass, phrase, expect}. The
    CALIBRATION deck writes its header as YAML comments and its rows flow-style; the HELD-OUT deck
    writes a real header and block-style rows. Neither is normalised here -- what is read is what the
    deck says."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = list(doc.get("rows") or [])
    if not rows:
        raise SystemExit(f"REFUSED: {path} carries no rows -- an empty deck certifies nothing.")
    bad = [r.get("id") for r in rows if not str(r.get("phrase") or "").strip()]
    if bad:
        raise SystemExit(f"REFUSED: rows with no phrase: {bad}")
    for r in rows:
        r["klass"] = str(r.get("klass") or r.get("class") or "").strip()
        r["expect"] = list(r.get("expect") or [])
    unknown = sorted({r["klass"] for r in rows} - set(CLASSES))
    if unknown:
        raise SystemExit(f"REFUSED: unknown class(es) {unknown} -- the bars are stated per class and a "
                         f"class with no bar would be scored silently under someone else's.")
    return {"path": path, "doc": doc, "rows": rows,
            "max_contracts": int(doc.get("max_contracts") or DEFAULT_MAX_CONTRACTS),
            "today": str(doc.get("today") or DEFAULT_TODAY)}


def deck_label(path: Path) -> str:
    """The deck's NAME, never its contents. A held-out deck is identified by its filename and its row
    count and by nothing that could carry a phrase into an artifact."""
    return path.name


def deck_identity(path: Path, deck: dict) -> dict:
    """WHICH DECK A RUN MEASURED, as a name and TWO DIGESTS -- the provenance half of the one-shot gate.

    A NAME IS NOT AN IDENTITY. `deck_label` answers "what was this file called", and the gate's real
    question is "which instrument produced these figures": v2 and v3 differ by ONE row, they carry the
    same class vocabulary, and a v2 run's own `class_counts` census is internally consistent -- so a
    gate stated over counts alone reads a clean v2 run (28 decoys, 90 non-decoy) as a satisfied v3 gate
    and opens on figures the v3 block was never measured by. A digest is the only field that cannot be
    satisfied by a deck that merely looks the part.

    TWO DIGESTS BECAUSE THEY ANSWER TWO QUESTIONS, and the gate grades the second:
      `deck_sha256`      -- the FILE's bytes, comments and all. A record: it names the file exactly as
                            it sat on disk, and it is what a reader months later diffs against.
      `deck_rows_sha256` -- the INSTRUMENT as this script read it: the parsed rows in deck order plus
                            the two header values a run's behaviour actually depends on
                            (`max_contracts`, `today`). A calibration deck writes its header as YAML
                            COMMENTS, and one of the things that header is for is recording the result
                            of the very run being certified -- so a gate pinned to the FILE digest
                            would close the moment the run it certified was written up, while the deck
                            that produced the figures had not moved a byte. This digest does not move
                            when prose does, and it moves the instant a row, a class, an expect list,
                            the contract tier or the as-of date does.

    BOTH ARE PHRASE-FREE OUTPUT, which is what lets them ride the in-tree bank on the same reasoning
    `planner_block_sha256` already rides it by: a hex digest carries no phrase, no row id and no
    expected id, and the held-out deck's rows stay outside the tree.

    The canonical form is sorted-key compact JSON with `default=str`, so a YAML date or an unordered
    mapping cannot make the same deck hash two ways on two runs."""
    payload = json.dumps({"rows": deck["rows"],
                          "max_contracts": deck["max_contracts"],
                          "today": deck["today"]},
                         sort_keys=True, ensure_ascii=False, default=str,
                         separators=(",", ":")).encode("utf-8")
    return {"deck": deck_label(path), "deck_path": str(path),
            "deck_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "deck_rows_sha256": hashlib.sha256(payload).hexdigest()}


def live_block_sha() -> str | None:
    """THE PIN THIS TREE SHIPS, or None when the module cannot be read. It is the COMPARAND half of
    the gate's PROVENANCE check and it is deliberately not the measured half.

    `state.subject.SUBJECT_BLOCK_SHA256` is the pin `config_check.check_subject_resolver` grades the
    live prompt against; here it is the thing a RUN's recorded sha is compared to. The import is local
    because this module is loaded by file location in the test deck and by `python scripts/...` on the
    console, and an unreadable module must be a stated decline (which fails the gate's provenance
    check) rather than an import error raised out of a grading function.

    WHY IT MAY READ A CONSTANT. Until 2026-09-11 BOTH sides of that check were this constant -- `main`
    recorded `SU.SUBJECT_BLOCK_SHA256` and this function read it back -- so the check compared a
    constant to itself and nothing in the runner hashed the text the run actually sends (MEASURED: a
    `_subject_block` rendering a DIFFERENT text still recorded the pin and the gate read OPEN). The
    RECORDED side is now a measurement made in `main` off `dispatch._subject_block` over the run's own
    `live_ids(graph)`, and a mismatch REFUSES before anything is billed or banked. With the recorded
    side measured, the pin is exactly the right comparand for a LATER grading -- a banked record
    re-read in a tree whose block has since moved must FAIL, and that is what this function is for."""
    try:
        from leviathan.graphrag.state import subject as _SU
        return str(_SU.SUBJECT_BLOCK_SHA256)
    except Exception:            # noqa: BLE001 -- an unreadable module is ungradable, never a pass
        return None


def live_graph_hash_or_none() -> str | None:
    """THE GRAPH AS IT STANDS IN THIS TREE, or None when it cannot be read. The third provenance
    input, and the one the block sha CANNOT stand in for.

    WHY A SEPARATE READING IS NEEDED AT ALL. The pinned planner block is substitution-free --
    MEASURED, `dispatch._subject_block(('a',))` and `_subject_block(('El_Nino',))` hash to the same
    text -- so the block sha names WHICH PROMPT and carries none of the enum the prompt is asked over.
    What the planner may pick is `subject.live_ids(graph)`, and THAT IS TWO INPUTS AND NOT ONE:
    `live_ids` is `all_ids(graph)` MINUS `subject.OWN_STRUCTURE_IDS`, so the GRAPH decides which ids
    exist and a module constant decides which of them are offered. `graph_hash` (the graph's
    `version`, stamped from the DAG YAML bytes) is the field that names the first half; the second is
    RECORDED on every run as `own_structure_fence` beside `live_ids_count`, which is what lets a
    reader of a bank tell a curation change (both counts move) from a fence change (only the enum
    does). A bank whose draws were made against a different graph is measuring a different enum, and
    no outcome, deck or block check can see that.

    IT IS THE LIVE VALUE AND NEVER A PIN. Unlike the deck, which is frozen for the certification, the
    graph is meant to move between sittings; the gate therefore asks "these draws were made against
    the graph this tree loads TODAY" and re-asks it on every grading. `live_graph_hash()` is called
    with NO graph argument -- MEASURED, it returns the same twelve characters as a loaded
    `CausalGraph`'s `version` in 0.29s -- so grading costs no graph load. `live_graph_hash` returns
    "" when the graph module cannot be read; that is mapped to None here so the gate reads it as an
    ABSENCE (fail-closed) rather than as a hash that happens to be empty."""
    try:
        from leviathan.graphrag.state import subject as _SU
        return str(_SU.live_graph_hash() or "") or None
    except Exception:            # noqa: BLE001 -- an unreadable graph is ungradable, never a pass
        return None


# ── the graph and the groups (shared by both layers) ─────────────────────────────────────────────
def load_graph():
    from leviathan.graphrag import graph as G
    g = G.CausalGraph.load()
    if len(getattr(g, "contracts", {}) or {}) < 24:
        raise SystemExit(f"REFUSED: the graph carries {len(g.contracts)} contracts -- a toy enum changes "
                         f"what the planner sees and the deck would certify nothing.")
    return g


def group_index(graph) -> tuple:
    """`(of_id, members_of_group)` -- the D4 subject groups, read from the ONE producer."""
    from leviathan.graphrag.state import subject as SU
    of_id = SU.groups(graph)
    inv: dict = collections.defaultdict(set)
    for i, k in of_id.items():
        inv[k].add(i)
    return of_id, inv


def expand(ids, of_id: dict, inv: dict) -> set:
    """Every id of every group the given ids belong to. A group-less id expands to itself."""
    out: set = set()
    for i in ids:
        k = of_id.get(i)
        out |= (inv.get(k) or {i}) if k else {i}
    return out


def group_keys(ids, of_id: dict) -> set:
    """The GROUP KEYS the ids belong to -- what `near_duplicate` and `multi` are scored over."""
    return {of_id.get(i) or f"id:{i}" for i in ids}


# ── LAYER 1 -- free, deterministic ───────────────────────────────────────────────────────────────
def layer1_rows(rows, *, graph, vocab) -> list:
    """One scoring pass per row. `floor=-1.0, top_k=40` records the FULL ranking so a miss's rank is
    recoverable offline; the FROZEN floors are applied at scoring time, never at collection time."""
    from leviathan.graphrag.state import subject as SU
    out = []
    t0 = time.perf_counter()
    for n, r in enumerate(rows):
        q = r["phrase"]
        ex = SU.exact_ids(q, graph)
        al = tuple(x for x in SU.alias_ids(q, graph) if x not in set(ex))
        cands, status = SU.semantic_candidates(q, graph, vocab=vocab, floor=-1.0, top_k=40)
        out.append({"id": r["id"], "klass": r["klass"], "expect": list(r["expect"]),
                    "exact": list(ex), "alias": list(al), "vocab_status": status,
                    "cands": [[c[0], round(float(c[1]), 6), c[2]] for c in cands]})
        if (n + 1) % 25 == 0:
            print(f"    layer 1: {n + 1}/{len(rows)} ({time.perf_counter() - t0:.1f}s)", flush=True)
    return out


def decline_words() -> frozenset:
    """The `vocab_status` words that mean THE SEMANTIC TIER DID NOT RUN ON THAT ROW.

    DERIVED FROM THE SHIPPED CLOSED SET, never typed out: everything in `HINT_STATUS_WORDS` that is
    not `ok` and not the DELIBERATE skip is a decline. A fifth word invented in `state/subject.py`
    therefore lands here as a decline by default -- fail-closed -- rather than being scored silently
    as if the tier had run."""
    from leviathan.graphrag.state import subject as SU
    return frozenset(w for w in SU.HINT_STATUS_WORDS if w not in ("ok", SU.STATUS_SKIPPED))


def instrument_census(scored: list) -> dict:
    """THE INSTRUMENT'S OWN LIVENESS, read off the PER-ROW status the tiers actually returned.

    WHY THIS EXISTS, and it is not hypothetical -- it was reproduced in this checkout minutes before
    the good run. `evidence.embed` raised inside its `sentence_transformers` import chain;
    `semantic_candidates` caught it (the embedder is allowed to be gone: T0/T1 are the fail-open
    floor) and returned `unreadable` with ZERO candidates on EVERY phrase -- while `load_vocab` in the
    same process returned `ok`, because that word grades THE FILE and the embedder is a different
    failure. The run scored, verdicted and banked itself with `artifact: ok` in its own header, every
    class at its lexical floor. At layer 2 the same state hands the planner `hints_line()` of an empty
    `SubjectHints`, which is the EMPTY STRING, and 312 or 330 calls are BILLED on a blank hint line.

    The held-out deck is a one-shot, spent-on-use asset and layer 2 is its only billed measurement, so
    a transient embed failure during that run would burn the money AND the set and leave behind an
    artifact that looks like a measurement. `run_latency` already embeds a sentinel before it times
    anything; this is the same belt on the deck path, and it is the reason the fence reads the ROWS
    and not the artifact."""
    c = collections.Counter(str(r.get("vocab_status") or "") for r in scored)
    dw = decline_words()
    declined = {w: n for w, n in sorted(c.items()) if w in dw}
    # THE COUNT KEY IS `rows_scanned` AND NOT `rows`: the in-tree bank's phrase-free pin
    # (`test_pb11`) bans the KEY `rows` structurally, because that is what a bar's ROW-ID LIST is
    # called. A count is not a map back into a held-out deck -- but the ban is a key ban on purpose,
    # so the census renames rather than the pin weakening.
    return {"rows_scanned": len(scored), "census": dict(sorted(c.items())),
            "decline_words": sorted(dw), "declined": declined,
            "declined_rows": sum(declined.values()),
            "live": not declined, "certifying": not declined}


def shipped_carry(scored: list, *, of_id: dict) -> dict:
    """THE CARRY THE ESTATE ACTUALLY TAKES, beside the raw candidate count the L1 decoy bar grades.

    A REPORT LINE AND NEVER A BAR (phase D). `score_layer1`'s decoy row counts every row with a
    candidate at or above AMBIG_FLOOR, which is what the floor was calibrated on and what the FATAL
    bar has always been stated over. Since phase D the SHIPPED path carries fewer of them, by two
    rules that live in the resolver and the seam rather than in this scorer:

      the FENCE     `SubjectHints.ambiguous` drops `state.subject.OWN_STRUCTURE_IDS` -- an id the
                    planner may not pick is not one a reader may be asked to choose.
      the GROUP     it collapses a group to its strongest member, so two spellings of one driver are
                    ONE entry ("either of two drivers" is true only when two GROUPS tie).
      the FREE-TIER a T0 or T1 hit on the phrase means the planner was shown the driver by name and
      DECLINE      declined anyway, which `state.seam._stamp_subject` reads as a decision rather than
                    an ambiguity, and no row is minted.

    So the two numbers answer two questions -- "how many rows put a strong candidate in front of the
    planner" and "how many rows would STOP A READER" -- and both are printed. THE BAR IS UNMOVED: it
    still grades the raw count, because retargeting a pre-registered bar inside the sitting whose
    change it grades is how an instrument stops being independent of the thing it measures. That
    retarget is a docket item and it is named in the report."""
    from leviathan.graphrag.state import subject as SU
    fenced, deduped, lexical, carried = [], [], [], []
    for r in scored:
        cands = tuple((c[0], float(c[1]), c[2]) for c in r["cands"])
        raw = [c for c in cands if c[1] >= SU.AMBIG_FLOOR]
        if not raw:
            continue
        h = SU.SubjectHints(exact=tuple(r["exact"]), alias=tuple(r["alias"]), candidates=cands,
                            groups=tuple((c[0], str(of_id.get(c[0]) or "")) for c in cands),
                            vocab_status=str(r["vocab_status"]))
        amb = h.ambiguous()
        if not amb:
            fenced.append(r["id"])
            continue
        if len(amb) < len(raw):
            deduped.append(r["id"])
        if r["exact"] or r["alias"]:
            lexical.append(r["id"])
            continue
        carried.append(r["id"])
    # COUNTS AND ROW LISTS ARE SEPARATE KEYS, and every list ends in `_rows` so the in-tree bank's
    # filter drops it by suffix: a held-out row id beside its class and its verdict is a map back
    # into a deck that must stay outside the tree (`test_pb11`'s rule, applied to a new key).
    klass = {r["id"]: r["klass"] for r in scored}
    return {"raw_rows_at_ambig_floor": len(fenced) + len(lexical) + len(carried),
            "carried": len(carried), "dropped_by_the_fence": len(fenced),
            "declined_on_a_free_tier_hit": len(lexical), "narrowed_by_the_group_key": len(deduped),
            # THE DECOY SPLIT, because the FATAL bar is stated over decoys alone: a carry on a TRUE
            # row is a turn where the planner is expected to pick anyway (`not picked` never holds),
            # while a carry on a driver-free ask is the row that bar exists to refuse.
            "decoy_carried": sum(1 for i in carried if klass.get(i) == "decoy"),
            "decoy_raw_at_ambig_floor": sum(1 for i in fenced + lexical + carried
                                            if klass.get(i) == "decoy"),
            "fenced_rows": sorted(fenced), "narrowed_rows": sorted(deduped),
            "lexical_rows": sorted(lexical), "carried_rows": sorted(carried)}


def fence_rescore(rows2: list, l1_rows: list) -> dict:
    """THE OWN-STRUCTURE FENCE APPLIED TO BANKED DRAWS -- free, offline, and a COUNTERFACTUAL.

    Phase C's billed layer 2 measured the picks a planner made with `calendar_spread` and `basis` in
    its enum. The fence removes them from the enum AND from the hint line, and `dispatch._validate`
    re-verifies a reply against the same vocabulary, so every banked pick of a fenced id is
    structurally impossible under it. That is what this counts, and it is a CEILING on what the fence
    removes rather than a prediction of the next run: what a planner does with the SHORTER list on
    those rows is exactly what no re-read of banked draws can answer, and the `counterfactual` field
    says so in the artifact."""
    from leviathan.graphrag.state import subject as SU
    F = set(SU.OWN_STRUCTURE_IDS)
    l1 = {r["id"]: r for r in l1_rows or []}
    dec_pick, dec_removed, dec_left, spurious, expected_lost = [], [], [], [], []
    draws_total = draws_pick = draws_removed = hint_rows = 0
    for r in rows2:
        a = l1.get(r["id"]) or {}
        top = [c[0] for c in (a.get("cands") or []) if c[1] >= SU.CAND_FLOOR][:SU.TOP_K]
        if (set(top) | set(a.get("exact") or ()) | set(a.get("alias") or ())) & F:
            hint_rows += 1
        picks = [tuple(dr.get("subject") or ()) for dr in r["draws"]]
        if r["klass"] == "decoy":
            draws_total += len(picks)
            n_any = sum(1 for p in picks if p)
            draws_pick += n_any
            if n_any:
                dec_pick.append(r["id"])
                n_after = sum(1 for p in picks if set(p) - F)
                draws_removed += n_any - n_after
                (dec_left if n_after else dec_removed).append(r["id"])
        elif any(set(p) & F for p in picks):
            (expected_lost if set(r["expect"] or ()) & F else spurious).append(r["id"])
    return {"fence": sorted(F), "counterfactual": True,
            "decoy": {"n": sum(1 for r in rows2 if r["klass"] == "decoy"),
                      "rows_that_picked": len(dec_pick),
                      "rows_removed_by_the_fence": len(dec_removed),
                      "removed_rows": sorted(dec_removed),
                      "rows_remaining": len(dec_left), "remaining_rows": sorted(dec_left),
                      "draws_total": draws_total, "draws_with_a_pick": draws_pick,
                      "draws_removed_by_the_fence": draws_removed,
                      "draws_remaining": draws_pick - draws_removed},
            "non_decoy": {"n": sum(1 for r in rows2 if r["klass"] != "decoy"),
                          "rows_losing_an_EXPECTED_id": len(expected_lost),
                          "expected_rows": sorted(expected_lost),
                          "rows_losing_a_SPURIOUS_second_pick": len(spurious),
                          "spurious_rows": sorted(spurious)},
            "hint_line": {"rows_whose_hint_line_carried_a_fenced_id": hint_rows,
                          "of_rows": len(rows2)}}


def score_layer1(scored: list, *, of_id: dict, inv: dict) -> dict:
    from leviathan.graphrag.state import subject as SU
    fl, am, k = SU.CAND_FLOOR, SU.AMBIG_FLOOR, SU.TOP_K

    def top(r, floor=fl):
        return [c for c in r["cands"] if c[1] >= floor][:k]

    def lex(r):
        return set(r["exact"]) | set(r["alias"])

    per: dict = {}
    agg = collections.Counter()
    for cl in CLASSES:
        rs = [r for r in scored if r["klass"] == cl]
        if not rs:
            continue
        if cl == "decoy":
            carry = [r["id"] for r in rs if top(r, am)]
            per[cl] = {"n": len(rs), "with_candidate": sum(1 for r in rs if top(r)),
                       "carried_at_ambig_floor": len(carry), "carried_ids": carry,
                       "bar": "carry == 0 (FATAL)",
                       "verdict": "PASS" if not carry else "FATAL"}
            continue
        a = h = at = 0
        for r in rs:
            want = expand(r["expect"], of_id, inv)
            t = top(r)
            a += bool(want & {c[0] for c in t})
            h += bool(t and t[0][0] in want)
            at += bool(want & (lex(r) | {c[0] for c in t}))
        bar = L1_BARS.get(cl)
        rate = at / len(rs)
        per[cl] = {"n": len(rs), "any_t2": a, "hit_at_1": h, "all_tiers": at,
                   "all_tiers_pct": round(_pct(at, len(rs)), 1),
                   "bar": (None if bar is None else f">= {bar:.0%}"),
                   "verdict": ("-" if bar is None else
                               ("PASS" if rate >= bar - 1e-9 else "MISS"))}
        agg["n"] += len(rs); agg["a"] += a; agg["h"] += h; agg["at"] += at
    return {"floors": {"CAND_FLOOR": fl, "AMBIG_FLOOR": am, "TOP_K": k},
            "per_class": per,
            "all_non_decoy": {"n": agg["n"], "any_t2": agg["a"], "hit_at_1": agg["h"],
                              "all_tiers": agg["at"],
                              "any_t2_pct": round(_pct(agg["a"], agg["n"]), 1),
                              "hit_at_1_pct": round(_pct(agg["h"], agg["n"]), 1),
                              "all_tiers_pct": round(_pct(agg["at"], agg["n"]), 1)},
            "lexical_baseline": dict(LEXICAL_BASELINE)}


# ── LAYER 2 -- the planner, billed ───────────────────────────────────────────────────────────────
def _usage_call(inner, rec: dict):
    """The `xc_fence.make_call` wrapper, plus the USAGE the dollar report is built from. `_call_opus`
    pop-tags `_usage` onto the returned dict (D-AM-4) and `_validate` ignores unknown keys, so the
    figures are read here rather than estimated from a per-call anchor."""
    def call(system, user, *, model, tool, **kw):
        rec["temperature"] = kw.get("temperature", "ABSENT")
        try:
            out = inner(system, user, model=model, tool=tool, **kw)
        except Exception as e:  # noqa: BLE001 -- recorded then re-raised (plan_turn maps it to fallback)
            rec["error"] = f"{type(e).__name__}: {e}"
            raise
        if isinstance(out, dict) and isinstance(out.get("_usage"), dict):
            rec["usage"] = dict(out["_usage"])
        return out
    return call


def usd(u: dict) -> float:
    """The BILLED dollars for one call, from the usage fields and the estate's own price table."""
    if not u:
        return 0.0
    from leviathan.graphrag import extract as ex
    return ex.Usage(input_tokens=int(u.get("in") or 0), output_tokens=int(u.get("out") or 0),
                    cache_creation=int(u.get("cache_write") or 0),
                    cache_read=int(u.get("cache_read") or 0)).cost_for(str(u.get("model") or SEAT))


def layer2_draw(row, *, graph, subject_ids, hints_line, inner_call, max_contracts, today) -> dict:
    """ONE `plan_turn` draw with the resolver's kwargs threaded -- the wiring `orchestrator.py` does
    under the flag, reproduced here argument for argument. A raise, a planner fallback or a degraded
    model marks the draw UNSCORED: an unscored row is never a passed row."""
    from leviathan.graphrag import dispatch as dp
    rec: dict = {}
    plan = dp.plan_turn(row["phrase"], graph=graph, today=today,
                        call=_usage_call(inner_call, rec), model=SEAT,
                        max_contracts=max_contracts,
                        subject_ids=subject_ids, subject_hints=hints_line)
    out = {"usage": rec.get("usage"), "temperature": rec.get("temperature"),
           "usd": round(usd(rec.get("usage") or {}), 6)}
    if rec.get("error"):
        return out | {"errored": rec["error"]}
    if plan.fallback:
        return out | {"errored": "planner_fallback (no raise)"}
    if plan.degraded:
        return out | {"errored": "degraded_model (Sonnet->Haiku)"}
    return out | {"subject": list(plan.subject), "subject_hints_n": int(plan.subject_hints_n),
                  "contracts": list(plan.contracts)}


def run_layer2(rows, *, graph, l1_by_id, draws, max_contracts, today, inner_call,
               meta: dict | None = None, cap_usd: float = HARD_CAP_USD) -> list:
    """THE BILLED PASS, with a RUNNING-TOTAL BREAKER as well as the pre-flight estimate.

    `main` already refuses when `calls x PER_CALL_USD` exceeds the cap -- the estate's "ceiling x
    requests vs balance BEFORE submit" doctrine, and the right first fence. But the anchor is $0.01 a
    call and nothing re-checked it once the run started, so a seat that billed far above the anchor
    would have run to the end of the deck and reported the overspend afterwards. The breaker reads the
    SAME usage fields the dollar report is built from, is checked between rows, and marks the run
    ABORTED so its bars can never be read as a completed measurement."""
    from leviathan.graphrag.state import subject as SU
    subject_ids = SU.live_ids(graph)
    meta = meta if meta is not None else {}
    meta.setdefault("spent", 0.0)
    meta.setdefault("aborted", False)
    out = []
    for row in rows:
        # THE HINT LINE IS REBUILT FROM LAYER 1's OWN SCORES, so the two layers cannot disagree about
        # what the planner was shown: the candidates are the frozen-floor top-5 of the same ranking
        # layer 1 recorded, and the exact/alias tiers are the same tuples.
        r1 = l1_by_id.get(row["id"]) or {}
        cands = tuple((c[0], float(c[1]), c[2]) for c in (r1.get("cands") or [])
                      if c[1] >= SU.CAND_FLOOR)[:SU.TOP_K]
        hints = SU.SubjectHints(exact=tuple(r1.get("exact") or ()), alias=tuple(r1.get("alias") or ()),
                                candidates=cands, vocab_status=str(r1.get("vocab_status") or "ok"))
        line = SU.hints_line(hints)
        reps = [layer2_draw(row, graph=graph, subject_ids=subject_ids, hints_line=line,
                            inner_call=inner_call, max_contracts=max_contracts, today=today)
                for _ in range(draws)]
        out.append({"id": row["id"], "klass": row["klass"], "expect": list(row["expect"]),
                    "hints_n": len(hints.ids()), "draws": reps})
        # AN ERRORED DRAW MUST NOT PRINT LIKE A CLEAN ONE. Both used to render `-`, which is the
        # decoy class's PASSING shape -- so a row whose every draw raised read on the console exactly
        # like a row the planner correctly declined, and the operator watching the billed run had no
        # tell at all. `ERR` is that tell; `score_layer2`'s `unscored` is the count behind it.
        picks = ["ERR" if d.get("errored") else ("/".join(d.get("subject") or []) or "-")
                 for d in reps]
        meta["spent"] = round(float(meta["spent"])
                              + sum(float(d.get("usd") or 0.0) for d in reps), 6)
        print(f"    {_ascii(row['id']):<10} {row['klass']:<14} picks={_ascii(','.join(picks))}"
              f"  ${meta['spent']:.4f}", flush=True)
        if meta["spent"] > cap_usd:
            meta["aborted"] = True
            print(f"    ABORTED: the running total ${meta['spent']:.4f} passed the "
                  f"${cap_usd:.2f} hard cap after {len(out)} of {len(rows)} rows. The remaining rows "
                  f"are UNSCORED and this run's bars are not a completed measurement.", flush=True)
            break
    return out


def concept_count(row: dict) -> int:
    """HOW MANY SEPARATE CAUSES THE ROW NAMES -- 1 for `near_duplicate` (the class IS one subject under
    several spellings), :data:`MULTI_MIN_CONCEPTS` for `multi`, or the length of a deck-declared
    `concepts:` list where a deck carries one. Every other class is scored on ids and never asks."""
    dec = row.get("concepts")
    if dec:
        return len(dec)
    return 1 if row.get("klass") == "near_duplicate" else MULTI_MIN_CONCEPTS


def _l2_hit(cl: str, got: list, *, want_ids: set, want_grp: set, n_concepts: int,
            of_id: dict, rule: str) -> bool:
    """ONE DRAW, under ONE of the two readings of a row's `expect` list. Both are computed on every
    run and both are reported: `shipped_v1` is what phase B measured, `alternatives` is the corrected
    reading and the one the verdict is taken on."""
    if rule == "shipped_v1":
        if cl == "multi":
            return want_grp <= group_keys(got, of_id)
        if cl == "near_duplicate":
            return bool(got) and group_keys(got, of_id) == want_grp
        return bool(set(got) & want_ids)
    if cl in ("multi", "near_duplicate"):
        return len(group_keys(got, of_id) & want_grp) == n_concepts
    return bool(set(got) & want_ids)


def score_layer2(rows: list, *, of_id: dict, inv: dict) -> dict:
    """A row PASSES at >= 2 of 3 SCORED draws (D9). Three different questions are asked of three
    different classes and they are not interchangeable:
      the id classes   -- the pick lands inside the expected id's GROUP (a near-duplicate id is the
                          same subject; D4 is the reason the group and not the id is the unit);
      near_duplicate   -- the pick's group equals ANY expected id's group, and only one of them;
      multi            -- every expected CONCEPT covered by some pick, and no cause named twice;
      decoy            -- ANY non-empty pick on ANY draw is a FIRE, and the bar is zero. FATAL.

    A ROW'S `expect` LIST IS A LIST OF ALTERNATIVES, AND THE FIRST CUT READ IT AS A CONJUNCTION. That
    is the correction this function carries, and it is a SCORER defect and never a resolver one --
    phase B's own draws prove it. The deck lists, for each cause the ask names, the ids that would all
    be RIGHT answers for it; the group index (`state.subject.groups`) merges most of those into one
    group but not all, because a group is a curated slice and two curated slices can hold two spellings
    of one cause. So:

      `near_duplicate` was scored `group_keys(pick) == group_keys(expect)`. On `nd03` the four
      positioning spellings sit in `slice:cftc_positioning` while `managed_money_positioning` sits in
      its own, and on `nd10` `India_export_ban` sits apart from the other three -- so the expected side
      was TWO groups and equality asked the planner to name a single subject with two group keys at
      once, which no pick can do. MEASURED: 4 of 10 under the old reading, 10 of 10 under this one, and
      the six that moved include three rows the planner answered with the single right id on 3 of 3
      draws. It was also failing rows for a SECOND pick outside the expected family (`nd01` adding
      `acreage_competition` to `fertilizer_costs` on a phrase that says 'next year acreage'), which is
      the MULTI class's question asked of a row that is not in it.

      `multi` was scored `group_keys(expect) <= group_keys(pick)` -- EVERY listed group. On `mu02`
      (`Argentina_export_tax` and `export_tax`, two spellings of one export-tax cause in two slices),
      `mu05` and `mu06` that demanded the planner name two spellings of ONE cause as two subjects,
      which the frozen block forbids in as many words ("Two names for ONE cause are not two subjects").
      MEASURED: 5 of 8 under the old reading, 8 of 8 under this one.

    THE CORRECTED READING IS NOT THE LOOSE ONE, and the equality is deliberate: the picks must reach
    EXACTLY `concept_count(row)` of the expected groups. One expected group for a `near_duplicate`
    means a planner that hedges across two alternative families still fails; exactly two for a `multi`
    means a planner that names one cause twice (three expected groups reached for two causes) fails
    too. What it stops charging for is a pick outside the expected families entirely -- which the
    per-row `foreign_picks` count records rather than scores, because on these classes it is a
    different question and one this deck does not bar."""
    per: dict = {}
    agg = collections.Counter()
    for cl in CLASSES:
        rs = [r for r in rows if r["klass"] == cl]
        if not rs:
            continue
        if cl == "decoy":
            # EVERY OTHER CLASS SPLITS SCORED FROM UNSCORED AND THIS ONE DID NOT -- and that omission
            # was FAIL-OPEN in the one place this estate can least afford it. `fired` is computed over
            # the NON-ERRORED draws, so a decoy row whose every draw raised contributed nothing to it
            # and the class still read {n: 27, fired: 0, verdict PASS}: a population that was never
            # asked the question read exactly like a population that answered it zero times, on the
            # FATAL bar, and on the field the held-out one-shot gate is stated over. The scored count
            # and the unscored row list are what make "0 of 27" a measurement rather than a silence.
            unscored = [r["id"] for r in rs if not any(not d.get("errored") for d in r["draws"])]
            fired = [r["id"] for r in rs
                     if any((d.get("subject") or []) for d in r["draws"] if not d.get("errored"))]
            per[cl] = {"n": len(rs), "scored": len(rs) - len(unscored), "unscored": unscored,
                       "fired": len(fired), "fired_ids": fired,
                       "bar": "0 picks on ANY draw (FATAL)",
                       # THE BAR IS STATED OVER THE WHOLE CLASS, so an UNSCORED row fails it exactly
                       # as a fired one does. An unasked row is not a row that answered zero.
                       "verdict": "PASS" if not (fired or unscored) else "FATAL"}
            continue
        passed, unscored, passed_v1, detail = [], [], [], []
        for r in rs:
            ok = [d for d in r["draws"] if not d.get("errored")]
            if not ok:
                unscored.append(r["id"])
                continue
            want_ids = expand(r["expect"], of_id, inv)
            want_grp = group_keys(r["expect"], of_id)
            n_con = concept_count(r)
            hits = {"alternatives": 0, "shipped_v1": 0}
            reached, foreign = set(), 0
            for d in ok:
                got = list(d.get("subject") or [])
                gk = group_keys(got, of_id)
                reached |= (gk & want_grp)
                foreign += len(gk - want_grp)
                for rule in hits:
                    hits[rule] += int(_l2_hit(cl, got, want_ids=want_ids, want_grp=want_grp,
                                              n_concepts=n_con, of_id=of_id, rule=rule))
            if hits["alternatives"] * 3 >= 2 * len(ok):
                passed.append(r["id"])
            if hits["shipped_v1"] * 3 >= 2 * len(ok):
                passed_v1.append(r["id"])
            if cl in ("multi", "near_duplicate"):
                detail.append({"id": r["id"], "concepts": n_con,
                               "expected_groups": len(want_grp), "groups_reached": len(reached),
                               "foreign_picks": foreign})
        n = len(rs) - len(unscored)
        bar = L2_BARS.get(cl)
        rate = (len(passed) / n) if n else 0.0
        per[cl] = {"n": len(rs), "scored": n, "passed": len(passed),
                   "passed_pct": round(_pct(len(passed), n), 1), "unscored": unscored,
                   # BOTH READINGS ON EVERY RUN. The verdict is taken on `passed` (the corrected
                   # ALTERNATIVES reading); `passed_shipped_v1` is what phase B's scorer would have
                   # said on the same draws, so a reader comparing this run against the banked one is
                   # never comparing two rules without being told.
                   "passed_shipped_v1": len(passed_v1),
                   "passed_shipped_v1_pct": round(_pct(len(passed_v1), n), 1),
                   "failed_ids": [r["id"] for r in rs
                                  if r["id"] not in passed and r["id"] not in unscored],
                   "bar": (None if bar is None else f">= {bar:.0%}"),
                   "verdict": ("-" if bar is None else
                               ("PASS" if (n and rate >= bar - 1e-9) else "MISS"))}
        if detail:
            per[cl]["group_detail"] = detail
        agg["n"] += n; agg["p"] += len(passed); agg["p1"] += len(passed_v1)
    calls = [d for r in rows for d in r["draws"]]
    # ── THE SEAT PIN, READ BACK RATHER THAN PRINTED. The report writes "temperature 0" from the module
    #    constant while `_usage_call` records what was ACTUALLY passed per draw, and nothing compared
    #    them: an assertion about the seat that never reads the seat is the exact class the
    #    TEMP_DEPRECATED_SEATS RCA exists to catch (a silent 14-of-14 fallback whose report still
    #    quoted the pin). The MODEL is read back the same way, from the usage the bill is computed on.
    _temps = sorted({repr(d.get("temperature")) for d in calls
                     if d.get("temperature") is not None}) or ["<none>"]
    _models = sorted({str((d.get("usage") or {}).get("model") or "") for d in calls
                      if d.get("usage")}) or ["<none>"]
    return {"per_class": per,
            "scoring_rule": {"reading": "alternatives", "also_reported": "shipped_v1",
                             "multi_min_concepts": MULTI_MIN_CONCEPTS,
                             "note": "a row's expect list is a list of ALTERNATIVES; the picks must "
                                     "reach EXACTLY concept_count(row) of the expected groups "
                                     "(near_duplicate 1, multi 2 unless the deck declares concepts)"},
            "all_non_decoy": {"scored": agg["n"], "passed": agg["p"],
                              "passed_pct": round(_pct(agg["p"], agg["n"]), 1),
                              "passed_shipped_v1": agg["p1"],
                              "passed_shipped_v1_pct": round(_pct(agg["p1"], agg["n"]), 1)},
            "calls": len(calls), "errored_calls": sum(1 for d in calls if d.get("errored")),
            "usd_measured": round(sum(float(d.get("usd") or 0.0) for d in calls), 4),
            # THE TWO HALVES ARE NOT THE SAME TEST AND THE RECORD SAYS SO. Temperature is compared
            # EXACTLY (`repr`, so `0` and `0.0` and "0" are three different observations); the model is
            # a FAMILY test -- the declared seat must appear as a SUBSTRING of every billed model id,
            # because a provider prefix (`us.anthropic.`) or a dated suffix is the same seat while a
            # different family is not. A reader of a PASS is entitled to know which question passed,
            # so the sentence rides the pin into the bar, the markdown and the gate's own readout.
            "seat_pin": {"temperature_declared": TEMPERATURE, "temperature_observed": _temps,
                         "seat_declared": SEAT, "model_observed": _models,
                         "model_test": (f"a model FAMILY test: {SEAT!r} must be a SUBSTRING of every "
                                        f"billed model id -- a provider prefix or a dated suffix "
                                        f"passes, another family does not"),
                         "temperature_test": "exact: every draw's recorded temperature repr",
                         "verdict": ("PASS" if (_temps == [repr(TEMPERATURE)]
                                                and all(SEAT in m for m in _models))
                                     else "STOP")},
            "lexical_baseline": dict(LEXICAL_BASELINE)}


# ── D10 -- the latency harness, free ─────────────────────────────────────────────────────────────
def run_latency(rows, *, graph, n: int) -> dict:
    """FLAG OFF vs FLAG ON over the deck's own phrases, at the seat the resolver actually occupies.

    THE TWO ARMS, and the arithmetic is the whole point:
      OFF  the walk embeds the verbatim query itself, COLD -- the turn pays that either way;
      ON   `resolve()` (which fills the same `evidence._Q_CACHE` key, so it pays the cold embed) plus
           `hints_line()` plus the walk's now-WARM embed of the same key.
    ADDED = ON - OFF, which is what D10's "<= 150 ms added per turn" is stated over. The resolver's own
    wall is banked beside it as `ms_board_subject_ms` -- that is the counter production sees, and it is
    dominated by an embed the walking lane was going to pay one call later.

    THE MEMO IS CLEARED BETWEEN EVERY DRAW. Phase A's first bank was measured warm and read 15 ms at
    p90; the same code measured cold reads 387. Clearing is what makes the two arms comparable.
    """
    from leviathan.graphrag import evidence as ev
    from leviathan.graphrag.state import subject as SU
    phrases = [r["phrase"] for r in rows][:max(1, int(n))]
    # THE MODEL LOAD AND THE ARTIFACT LOAD ARE PAID BEFORE THE FIRST DRAW, on a sentinel phrase that is
    # in no deck. Both are ONCE PER PROCESS (the bge-m3 weights; the 25 MB np.load and its blurb index)
    # and both are declared OUTSIDE every figure here -- leaving them inside draw 1 would put a
    # thirty-second one-time cost into the OFF arm and make the mean of `added` negative, which is a
    # number no reader can use even when the percentiles are unharmed.
    ev._Q_CACHE.clear()
    _sentinel = "a warm-up phrase that belongs to no deck row"
    try:
        ev.embed([_sentinel])
    except Exception as e:  # noqa: BLE001 -- a clean refusal, never a traceback with timings behind it
        raise SystemExit(f"REFUSED: the embedder is unavailable ({type(e).__name__}: {e}) -- the OFF "
                         f"arm is a cold embed and the ON arm is that same embed plus resolve(), so "
                         f"a dead embedder measures nothing. Nothing was banked.")
    # AND THE SENTINEL'S OWN STATUS IS READ, the deck path's instrument fence in one row: `resolve()`
    # swallows an embed failure by contract (T0/T1 are the fail-open floor), so a tier that declined
    # here would otherwise be timed as if it had run and banked as a 0 ms addition.
    _h = SU.resolve(_sentinel, graph=graph)
    if _h.vocab_status in decline_words():
        raise SystemExit(f"REFUSED: the sentinel resolve declined with vocab_status "
                         f"{_h.vocab_status!r} -- the semantic tier is not running, so the ON arm is "
                         f"the OFF arm and the added wall would bank as ~0. Nothing was banked.")
    SU.hints_line(_h)
    off, on, added, resolver_ms, hints_ms = [], [], [], [], []
    for i, q in enumerate(phrases):
        ev._Q_CACHE.clear()                                # the OFF arm: the walk pays the cold embed
        t = time.perf_counter()
        ev.embed([q])
        d_off = (time.perf_counter() - t) * 1000.0
        ev._Q_CACHE.clear()                                # the ON arm: the resolver pays it first
        t = time.perf_counter()
        h = SU.resolve(q, graph=graph)
        d_res = (time.perf_counter() - t) * 1000.0
        t = time.perf_counter()
        SU.hints_line(h)
        d_hint = (time.perf_counter() - t) * 1000.0
        t = time.perf_counter()
        ev.embed([q])                                      # the walk's own embed, now a memo hit
        d_warm = (time.perf_counter() - t) * 1000.0
        d_on = d_res + d_hint + d_warm
        off.append(d_off); on.append(d_on); added.append(d_on - d_off)
        resolver_ms.append(float(h.ms)); hints_ms.append(d_hint)
        if (i + 1) % 10 == 0:
            print(f"    latency: {i + 1}/{len(phrases)}  added p90 so far "
                  f"{_pctile(added, 0.90):.1f} ms", flush=True)

    def stat(xs):
        return {"p50": round(_pctile(xs, 0.50), 2), "p90": round(_pctile(xs, 0.90), 2),
                "mean": round(statistics.fmean(xs), 2) if xs else 0.0, "n": len(xs)}

    # THE BUDGET IS READ FROM THE GRADER, NOT TYPED HERE. `config_check.SUBJECT_LATENCY_BUDGET_MS` is
    # the one place D10's 150 ms lives; clause (13) grades the banked p90 against it AND reds when the
    # bank's own `budget_ms` disagrees with it. Writing the figure from that constant is what makes the
    # disagreement check a tripwire for drift rather than a second chance to invent a threshold.
    from leviathan.graphrag.config_check import SUBJECT_LATENCY_BUDGET_MS as _BUDGET
    return {"budget_ms": float(_BUDGET), "n": len(phrases),
            "flag_off_turn_embed_ms": stat(off), "flag_on_total_ms": stat(on),
            "added_wall_per_turn_ms": stat(added),
            "ms_board_subject_ms": stat(resolver_ms), "hints_line_ms": stat(hints_ms),
            "bar": {"metric": "added_wall_per_turn_ms.p90", "budget_ms": float(_BUDGET),
                    "measured_ms": round(_pctile(added, 0.90), 2),
                    "verdict": "PASS" if _pctile(added, 0.90) <= float(_BUDGET) else "STOP"},
            "note": ("OFF = the walk's own cold embed of the verbatim query, which the turn pays "
                     "either way. ON = resolve() (cold, it fills the same _Q_CACHE key) + hints_line() "
                     "+ the walk's now-warm embed. ADDED is the difference and is what D10 budgets. "
                     "ms_board_subject_ms is the resolver's OWN wall -- the production counter -- and "
                     "is dominated by that shared embed. THE LANE SPLIT IS STATED AND NOT HIDDEN: "
                     "these figures are a WALKING lane's. A lane that never walks (numbers_only, "
                     "trivial) pays ms_board_subject_ms in full and nobody pays it back, which is "
                     "what resolve(allow_embed=False) is for -- and which the orchestrator cannot "
                     "decide at this call site, because the lane is plan_turn's own output (D10 "
                     "addendum A1). The model load and the artifact load are once per process and "
                     "sit outside every figure here: both are paid on a sentinel phrase first."),
            "lane_split": {"walking_lane_added_p90": round(_pctile(added, 0.90), 2),
                           "never_walking_lane_added_p90": round(_pctile(resolver_ms, 0.90), 2)}}


# ── the report ───────────────────────────────────────────────────────────────────────────────────
def markdown(doc: dict) -> str:
    L = []
    L.append(f"# SUBJECT RESOLVER DECK RUN -- {doc['deck']}")
    L.append("")
    L.append(f"- generated: {doc['generated_utc']}")
    L.append(f"- rows: {doc['rows_total']}  graph: {doc['graph_hash']}  "
             f"artifact: {doc['vocab_status']}")
    # THE INSTRUMENT, BESIDE THE ARTIFACT AND NOT INSTEAD OF IT. `artifact: ok` grades the FILE; this
    # line grades whether the semantic tier actually RAN, row by row, which is the half a dead embedder
    # takes away while the header above still reads 'ok'.
    _inst = doc.get("instrument")
    if _inst:
        L.append(f"- instrument: {'LIVE' if _inst['live'] else 'DEAD'} -- per-row vocab_status "
                 f"{_inst['census']} over {_inst['rows_scanned']} rows"
                 + ("" if _inst["live"] else "  **NON-CERTIFYING**"))
    # THE PROMPT THESE FIGURES MEASURED, on the face of the report. Every deck header says a run whose
    # block sha is not the stamped one measures a different text; a report that does not print its own
    # leaves that comparison to a commit date.
    if doc.get("planner_block_sha256"):
        L.append(f"- planner block sha256: {doc['planner_block_sha256']}")
    # AND WHICH DECK THEY WERE MEASURED ON. The name is at the top of this report and a name is not an
    # identity: v2 and v3 differ by one row and carry the same class vocabulary, so the row digest is
    # what tells two runs apart. The file digest rides beside it because the file is what a reader
    # diffs; neither carries a phrase.
    if doc.get("deck_rows_sha256"):
        L.append(f"- deck rows sha256: {doc['deck_rows_sha256']}"
                 + (f"  (file {doc['deck_sha256']})" if doc.get("deck_sha256") else ""))
    # AND WHICH RUN EACH *CARRIED* BLOCK WAS MEASURED BY. A dated summary MERGES: a layer this run did
    # not measure keeps its banked figures, and until this stamp rode beside them the full provenance
    # header above sat over a table measured by an earlier run. It is printed here, at the top, rather
    # than left to a reader to notice section by section.
    for _ck, _clabel in (("layer1", "LAYER 1"), ("layer2", "the legacy LAYER 2 block"),
                         ("latency", "the D10 LATENCY harness")):
        _cat = doc.get(f"{_ck}_generated_utc")
        if _cat and _cat != doc.get("generated_utc"):
            L.append(f"- **{_clabel} was MEASURED at {_cat}** and is CARRIED into this merged "
                     f"summary: every provenance line above names the LATEST run on this deck and "
                     f"date, and not that block")
    L.append(f"- layers run: {', '.join(doc['layers_run']) or 'none'}")
    L.append(f"- verdict vocabulary: {{LAND-DARK, STOP}} -- this deck cannot flip anything")
    L.append("")
    l1 = doc.get("layer1")
    if l1:
        L.append("## LAYER 1 -- the deterministic tiers (free)")
        L.append("")
        L.append(f"floors FROZEN: CAND {l1['floors']['CAND_FLOOR']}  "
                 f"AMBIG {l1['floors']['AMBIG_FLOOR']}  TOP_K {l1['floors']['TOP_K']}")
        L.append("")
        L.append("| class | n | anyT2 | hit@1 | all-tiers | bar | verdict |")
        L.append("|---|---|---|---|---|---|---|")
        for cl, v in l1["per_class"].items():
            if cl == "decoy":
                L.append(f"| decoy | {v['n']} | cand={v['with_candidate']} | "
                         f"carry={v['carried_at_ambig_floor']} | - | {v.get('bar') or '-'} | "
                         f"{v.get('verdict', '-')} |")
            else:
                L.append(f"| {cl} | {v['n']} | {v['any_t2']}/{v['n']} | {v['hit_at_1']}/{v['n']} | "
                         f"{v['all_tiers']}/{v['n']} ({v['all_tiers_pct']}%) | "
                         f"{v.get('bar') or '-'} | {v.get('verdict', '-')} |")
        a = l1["all_non_decoy"]
        L.append(f"| ALL non-decoy | {a['n']} | {a['any_t2_pct']}% | {a['hit_at_1_pct']}% | "
                 f"{a['all_tiers_pct']}% | - | - |")
        L.append("")
        L.append(f"lexical baseline, like for like: {LEXICAL_BASELINE['any_hit_pct']}% any-hit / "
                 f"{LEXICAL_BASELINE['hit_at_1_pct']}% hit@1 -- {LEXICAL_BASELINE['note']}")
        L.append("")
        # WHICH COLUMN THE BARS ARE GRADED ON, said once and in the report rather than left to the
        # reader of `score_layer1`. D9's sentence for synonym/misspelling/description/acronym says "in
        # the top-5 candidates"; the graded column is the union of ALL THREE TIERS (T0 exact, T1 alias,
        # and that top-5), which is more permissive than the literal wording. Both columns are printed
        # above precisely so the difference is visible: on the calibration deck they coincide on every
        # graded class; on the held-out deck they differ on synonym and description, and NO bar's
        # verdict changes under either reading (checked on both decks).
        L.append("BARS ARE GRADED ON THE `all-tiers` COLUMN -- T0 exact UNION T1 alias UNION the "
                 "frozen-floor top-5 -- which is wider than D9's literal 'in the top-5 candidates'. "
                 "The `anyT2` column beside it is the strict top-5 reading; no bar's verdict differs "
                 "between the two on either deck.")
        L.append("")
        # THE TWO READINGS OF "A CARRY", printed together for the reason the layer-2 scorer prints
        # its two: one of them is what the bar grades and the other is what a reader would meet.
        sc = l1.get("shipped_carry")
        if sc:
            L.append(f"THE SHIPPED CARRY, beside the bar's raw count: **{sc['carried']} of "
                     f"{sc['raw_rows_at_ambig_floor']}** rows at AMBIG_FLOOR would STOP A READER, "
                     f"and **{sc['decoy_carried']} of {sc['decoy_raw_at_ambig_floor']}** of the "
                     f"DECOY rows the FATAL bar is stated over. The fence drops "
                     f"{sc['dropped_by_the_fence']}, the free-tier decline drops "
                     f"{sc['declined_on_a_free_tier_hit']}, and the group key narrows "
                     f"{sc['narrowed_by_the_group_key']}. THE BAR ABOVE IS "
                     f"UNMOVED and still grades the RAW count: retargeting a pre-registered bar "
                     f"inside the sitting whose change it grades is how an instrument stops being "
                     f"independent of what it measures. Pointing it at `SubjectHints.ambiguous` plus "
                     f"the seam's rule is a DOCKET item.")
            L.append("")
    l2 = doc.get("layer2")
    if l2:
        L.append("## LAYER 2 -- the planner (billed)")
        L.append("")
        L.append(f"seat {SEAT}  temperature {TEMPERATURE}  max_contracts {doc['max_contracts']}  "
                 f"draws {doc['draws']}  (a row passes at >= 2 of {doc['draws']})")
        L.append("")
        L.append("| class | n | scored | passed (alternatives) | passed (shipped v1) | bar | verdict |")
        L.append("|---|---|---|---|---|---|---|")
        for cl, v in l2["per_class"].items():
            if cl == "decoy":
                # THE DECOY ROW CARRIES ITS `scored` COUNT LIKE EVERY OTHER ROW. It printed `-` while
                # the class kept no such count, and a dash in the one column that says whether the
                # question was asked is where "0 of 27 fired" reads as a clean bar on a run that
                # measured nothing. A bank written before the count existed still prints `-`.
                # AND EVERY CELL IS READ WITH `.get`. This row renders BANKED documents as well as
                # live ones -- the banked markdown is rendered from the sanitised summary, and a
                # per-class block written by an older shape can lack any of these keys. A KeyError
                # here is a report that does not exist beside a JSON half that does, which is the one
                # failure a reporting function must not have.
                L.append(f"| decoy | {v.get('n', '-')} | {v.get('scored', '-')} | "
                         f"fired={v.get('fired', '-')} | fired={v.get('fired', '-')} | "
                         f"{v.get('bar') or '-'} | {v.get('verdict', '-')} |")
            else:
                L.append(f"| {cl} | {v.get('n', '-')} | {v.get('scored', '-')} | "
                         f"{v.get('passed', '-')} ({v.get('passed_pct', '-')}%) | "
                         f"{v.get('passed_shipped_v1', '-')} "
                         f"({v.get('passed_shipped_v1_pct', '-')}%) | "
                         f"{v.get('bar') or '-'} | {v.get('verdict', '-')} |")
        # AND THE TOTAL ROW READS WITH `.get` LIKE EVERY ROW ABOVE IT. This was the LAST bare index
        # left in a function that renders BANKED documents as well as live ones, and it was the one
        # that fired: the real 2026-09-10 v1 bank carries an `all_non_decoy` of
        # {scored, passed, passed_pct} -- written before the `shipped v1` column existed -- and the
        # merge CARRIES that legacy block onto every later run's summary (layer 2 never rides a new
        # summary, so the preserve loop always fires). MEASURED, end to end through the fake transport:
        # `--deck subject_deck_v1.yaml --layer 2 --bank-dir <copy of data/subject_resolver/2026-09-10>`
        # raised `KeyError: 'passed_shipped_v1'` AFTER the immutable record was on disk and BEFORE the
        # pointer entry -- a real layer-2 attempt that the attempt count did not count, and a bank
        # whose two halves disagreed. Twice over: two runs, two records, zero pointers.
        a = l2.get("all_non_decoy") or {}
        L.append(f"| ALL non-decoy | - | {a.get('scored', '-')} | "
                 f"{a.get('passed', '-')} ({a.get('passed_pct', '-')}%) | "
                 f"{a.get('passed_shipped_v1', '-')} "
                 f"({a.get('passed_shipped_v1_pct', '-')}%) | - | - |")
        L.append("")
        # BOTH READINGS, AND WHICH ONE THE VERDICT IS TAKEN ON. The two columns differ only on
        # `near_duplicate` and `multi`, whose `expect` lists are ALTERNATIVES rather than conjunctions;
        # every other class is scored identically under both, which is why the difference is a scorer
        # correction and not a re-grading of the wave.
        _sr = l2.get("scoring_rule") or {}
        L.append("THE VERDICT COLUMN IS `alternatives` -- a row's `expect` list names, for each cause "
                 "the ask carries, the ids that would each be a right answer for it, and the picks "
                 "must reach EXACTLY the row's concept count among the expected groups "
                 f"(near_duplicate 1, multi {_sr.get('multi_min_concepts', MULTI_MIN_CONCEPTS)} "
                 "unless the deck declares `concepts:`). `shipped v1` is the same draws under phase "
                 "B's scorer, which read the list as a CONJUNCTION and so asked one pick to carry two "
                 "group keys at once; the two columns coincide on every class but those two.")
        L.append("")
        # THE MONEY LINE READS WITH `.get` TOO, AND THE FORMAT SPEC IS GUARDED. `${x:.4f}` on a
        # `.get` that returned None is a TypeError one line further down -- the same crash wearing a
        # different name -- so an absent figure is printed as the absence it is. A dash here says
        # "this bank did not record it"; a zero would say "this run measured none", and on a money
        # line those are not the same claim.
        _usd = l2.get("usd_measured")
        _usd_s = (f"${_usd:.4f}" if isinstance(_usd, (int, float)) and not isinstance(_usd, bool)
                  else "$- (not recorded by the run that wrote this block)")
        L.append(f"calls {l2.get('calls', '-')} (errored {l2.get('errored_calls', '-')}), "
                 f"MEASURED {_usd_s} from the usage fields")
        _sp = l2.get("seat_pin")
        if _sp:
            L.append("")
            L.append(f"SEAT PIN, read back from the draws (never only printed): temperature "
                     f"declared {_sp['temperature_declared']} / observed "
                     f"{', '.join(_sp['temperature_observed'])}; seat declared {_sp['seat_declared']} "
                     f"/ billed {', '.join(_sp['model_observed'])} -- {_sp['verdict']}"
                     + (f". The model half is {_sp['model_test']}."
                        if _sp.get("model_test") else ""))
        if l2.get("aborted_on_cost"):
            L.append("")
            L.append("**ABORTED ON COST**: the running total passed the hard cap mid-run, the "
                     "remaining rows are unscored, and these bars are not a completed measurement.")
        L.append("")
    # THE GATE ON THE FACE OF THE REPORT, under its own heading and in its own vocabulary. A reader
    # who opens this file months from now should not have to reconstruct which layer-2 fields the
    # one-shot was spent (or withheld) on, nor reconcile the gate against a run verdict that answers
    # a different question.
    # THE LAYER-2 RUNS ON THIS DECK AND DATE, BY POINTER. A merged summary is an INDEX and this is the
    # index: every layer-2 run on this deck and date is one immutable file, named here beside the
    # provenance it carries, and the number of entries IS the number of attempts -- which nothing in
    # the tree counted until this list existed.
    _runs = doc.get("layer2_runs")
    if isinstance(_runs, list):
        L.append(f"## THE LAYER-2 RUNS BANKED ON THIS DECK AND DATE -- {len(_runs)}")
        L.append("")
        # THE RECORD'S OWN DIGEST RIDES THE TABLE, because it is the one field here that is not a copy
        # of something inside the file it names -- it is the witness to what that file's BYTES were
        # when this row was written, and `--grade-record` refuses a record that no longer hashes to
        # it. A reader comparing a bank months later needs it on the face of the report, not only in
        # the JSON. A row written before the field existed prints `-`.
        L.append("| # | file | record sha | stamp | block sha | graph | deck rows | "
                 "draws x rows = calls | errored | $ | gate |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(_runs, start=1):
            if not isinstance(r, dict):
                continue
            L.append(f"| {i} | `{r.get('file', '-')}` | "
                     f"{str(r.get('record_sha256') or '-')[:12]} | {r.get('generated_utc', '-')} | "
                     f"{str(r.get('planner_block_sha256') or '-')[:12]} | "
                     f"{r.get('graph_hash', '-')} | "
                     f"{str(r.get('deck_rows_sha256') or '-')[:12]} | "
                     f"{r.get('draws', '-')} x {r.get('rows_total', '-')} = {r.get('calls', '-')} | "
                     f"{r.get('errored_calls', '-')} | {r.get('usd_measured', '-')} | "
                     f"{r.get('gate_verdict', '-')} |")
        L.append("")
        L.append("EACH FILE IS WRITTEN ONCE AND NEVER MERGED INTO, and each carries its own "
                 "provenance BESIDE the measurement that provenance describes. THIS SUMMARY IS NOT A "
                 "CERTIFICATE: it is a fixed path per deck per date and it merges, so the header at "
                 "the top of this report names the LATEST run on this deck and date -- neither the "
                 "LAYER 1 table above, which is carried forward from whichever run last measured it "
                 "(its own stamp rides `layer1_generated_utc`, and is printed in the header when it "
                 "differs), nor the layer 2 in any of the files above. The one-shot gate is graded on "
                 "a per-run record and refuses this document by its artifact class. THE ATTEMPT "
                 "COUNT IS THE LENGTH OF THIS LIST.")
        L.append("")
    _gl = doc.get("oneshot_gate_latest")
    if isinstance(_gl, dict):
        L.append(f"THE LATEST GATE VERDICT, COPIED FOR A HUMAN READER: **{_gl.get('verdict', '-')}** "
                 f"on `{_gl.get('file', '-')}` (stamped {_gl.get('generated_utc', '-')})"
                 + ("" if not _gl.get("failing")
                    else " -- failing: " + "; ".join(str(x) for x in _gl["failing"]))
                 + ". It is a COPY and it names its own file: grade the file, never this line.")
        L.append("")
    _g = doc.get("oneshot_gate")
    if _g:
        L.append(f"## THE HELD-OUT ONE-SHOT GATE -- {_g['verdict']}")
        L.append("")
        if doc.get("layer2_record_file"):
            L.append(f"computed on the per-run record `{doc['layer2_record_file']}`")
            L.append("")
        L.append(f"`{_g['gate']}`. This is NOT the run verdict and it is NOT the exit code: the exit "
                 "code grades every evaluated bar together, layer 1's FATAL decoy carry included, and "
                 "the deck header authorises reading past that carry because the block is graded on "
                 "the layer-2 bar. The gate is graded on the layer-2 fields plus the run's own "
                 "PROVENANCE, SHAPE and STANDING -- which prompt the draws were made under, which "
                 "deck they were drawn on, which GRAPH they were drawn against (the prompt is "
                 "substitution-free, so the enum is `live_ids` of the graph minus the own-structure "
                 "fence and not the block's), whether every row was drawn the pre-registered three "
                 "times, whether this is the run itself rather than a re-score of one, and -- first "
                 "of all -- whether the document it was handed is a PER-RUN RECORD rather than a "
                 "merged summary whose provenance a later run can overwrite. It is asked of the "
                 "CALIBRATION run, so a run on any other deck holds it by construction.")
        L.append("")
        L.append("| check | measured | verdict |")
        L.append("|---|---|---|")
        for c in _g["checks"]:
            L.append(f"| {c['check']} | {c['measured']} | {'PASS' if c['pass'] else 'FAIL'} |")
        L.append("")
        L.append(f"**GATE {_g['verdict']}** -- "
                 + ("every pre-registered check passed; the held-out one-shot may be run ONCE."
                    if _g["verdict"] == "OPEN"
                    else "failing: " + "; ".join(_g["failing"]) + ". The one-shot is NOT spent."))
        L.append("")
    lat = doc.get("latency")
    if lat:
        L.append("## D10 -- the latency bar (free)")
        L.append("")
        L.append("| population | p50 ms | p90 ms | n |")
        L.append("|---|---|---|---|")
        for k in ("flag_off_turn_embed_ms", "flag_on_total_ms", "added_wall_per_turn_ms",
                  "ms_board_subject_ms", "hints_line_ms"):
            v = lat[k]
            L.append(f"| {k} | {v['p50']} | {v['p90']} | {v['n']} |")
        L.append("")
        L.append(f"BAR {lat['bar']['metric']} <= {lat['bar']['budget_ms']:.0f} ms: measured "
                 f"{lat['bar']['measured_ms']} ms -- {lat['bar']['verdict']}")
        L.append("")
        L.append(lat["note"])
        L.append("")
    fr = doc.get("fence_rescore")
    if fr:
        d, n = fr["decoy"], fr["non_decoy"]
        L.append("## THE OWN-STRUCTURE FENCE, APPLIED TO THESE DRAWS (free, a COUNTERFACTUAL)")
        L.append("")
        L.append(f"fence: {', '.join(fr['fence'])} -- removed from the enum, from the hint line and "
                 f"from the ambiguity carry (`state.subject.OWN_STRUCTURE_IDS`)")
        L.append("")
        L.append(f"- DECOY: {d['rows_that_picked']} of {d['n']} rows picked a subject on at least "
                 f"one draw; the fence removes {d['rows_removed_by_the_fence']} of them "
                 f"({', '.join(d['removed_rows']) or 'none'}), leaving {d['rows_remaining']} "
                 f"({', '.join(d['remaining_rows']) or 'none'}).")
        L.append(f"- DECOY DRAWS: {d['draws_with_a_pick']} of {d['draws_total']} carried a pick; "
                 f"{d['draws_removed_by_the_fence']} are structurally impossible under the fence, "
                 f"{d['draws_remaining']} remain.")
        L.append(f"- TRUE ROWS: {n['rows_losing_an_EXPECTED_id']} of {n['n']} lose an EXPECTED id "
                 f"({', '.join(n['expected_rows']) or 'none'}); "
                 f"{n['rows_losing_a_SPURIOUS_second_pick']} lose a SPURIOUS second pick and keep "
                 f"the expected one ({', '.join(n['spurious_rows']) or 'none'}).")
        L.append(f"- HINT LINE: {fr['hint_line']['rows_whose_hint_line_carried_a_fenced_id']} of "
                 f"{fr['hint_line']['of_rows']} rows had a fenced id on the line the planner read.")
        L.append("")
        L.append("IT IS A CEILING ON WHAT THE FENCE REMOVES AND NOT A PREDICTION. The banked picks "
                 "of a fenced id cannot be made under it -- the enum never offers the id and "
                 "`_validate` drops it from a reply that names one anyway -- but what a planner does "
                 "with the SHORTER list on those rows is what no re-read of banked draws can answer, "
                 "and it is the next billed run's first obligation.")
        L.append("")
    L.append("## BARS")
    L.append("")
    for b in doc["bars"]:
        L.append(f"- **{b['verdict']}** {b['bar']} -- {b['detail']}"
                 + (f" [rows: {', '.join(b['rows'])}]" if b.get("rows") else ""))
    L.append("")
    L.append(f"## VERDICT: {doc['verdict']}")
    if doc.get("failing_bars"):
        L.append("")
        L.append("failing bars: " + "; ".join(doc["failing_bars"]))
    return "\n".join(L) + "\n"


def collect_bars(doc: dict) -> list:
    """Every EVALUATED bar as {bar, verdict, detail, rows}. A layer that did not run yields no bar --
    a bar that was never measured is never reported as passed.

    `detail` IS COUNTS ONLY AND `rows` IS THE ROW IDS, and the split is the phrase-free rule applied to
    its nearest neighbour: a held-out row id beside its class and its verdict is a map back into a deck
    that must stay outside the tree. The scratchpad artifact and stdout carry `rows`; the in-tree bank
    drops it. Naming the failing rows on the console is what makes a MISS actionable, so the split is
    where the artifact is written and not where the measurement is made."""
    bars = []
    l1 = doc.get("layer1")
    if l1:
        for cl, v in l1["per_class"].items():
            if cl == "decoy":
                bars.append({"bar": "L1 DECOY CARRY (0 at AMBIG_FLOOR, FATAL)",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "STOP",
                             "detail": f"{v['carried_at_ambig_floor']} of {v['n']} decoys carried "
                                       f"({v['with_candidate']} put a candidate above CAND_FLOOR in "
                                       f"front of the planner)",
                             # THE ROW LISTS ARE READ WITH `.get`: this function is handed the
                             # FULL block today, and the sanitised one (whose `*_ids` lists are
                             # dropped as a map back into a deck) is one caller away.
                             "rows": list(v.get("carried_ids") or [])})
            elif v.get("bar"):
                bars.append({"bar": f"L1 {cl.upper()} {v['bar']}",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "MISS",
                             "detail": f"{v['all_tiers']}/{v['n']} = {v['all_tiers_pct']}% all-tiers",
                             "rows": []})
    l2 = doc.get("layer2")
    if l2:
        for cl, v in l2["per_class"].items():
            if cl == "decoy":
                # THE SCORED COUNT RIDES IN THE DETAIL, because "0 of 27 fired" is a figure a reader
                # will take as a clean bar and it is only that when 27 rows were actually asked.
                _dsc = v.get("scored")
                _ddet = (f"{v['fired']} of {v['n']} decoy rows had the planner pick a subject on at "
                         f"least one draw")
                if _dsc is None:
                    # AND AN ABSENT CENSUS IS SAID OUT LOUD RATHER THAN LEFT AS SILENCE. A bank
                    # written before `scored` existed rendered the bare "0 of 27 decoy rows picked a
                    # subject" line -- which is the sentence a PERFECT decoy bar prints, on a run
                    # whose denominator is unknown. The two readings are opposite and the line could
                    # not be told apart; now the missing half names itself.
                    _ddet += ("; the run recorded NO scored census for the decoy class -- the figure "
                              "above is over an UNKNOWN denominator and is not a clean bar")
                elif _dsc == v["n"]:
                    _ddet += f"; all {v['n']} rows were SCORED"
                else:
                    _ddet += (f"; only {_dsc} of {v['n']} rows were SCORED -- the rest had EVERY "
                              f"draw error, and an unasked row is not a row that answered zero")
                bars.append({"bar": "L2 DECOY PICKS (0 on ANY draw, FATAL)",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "STOP",
                             "detail": _ddet,
                             "rows": list(v.get("fired_ids") or [])})
            elif v.get("bar"):
                bars.append({"bar": f"L2 {cl.upper()} {v['bar']}",
                             "verdict": "PASS" if v["verdict"] == "PASS" else "MISS",
                             "detail": f"{v['passed']}/{v['scored']} = {v['passed_pct']}% at "
                                       f">= 2 of {doc['draws']} draws",
                             "rows": list(v.get("failed_ids") or [])})
        # THE SEAT PIN AS A BAR, because the report used to ASSERT it and never READ it. A seat that
        # moved would move the treatment with it and nothing measured here would be attributable.
        _sp = l2.get("seat_pin")
        if _sp:
            bars.append({"bar": "L2 SEAT PIN (temperature and model, read back from every draw)",
                         "verdict": _sp["verdict"],
                         # THE DETAIL NAMES THE TEST AND NOT ONLY THE FIGURES. The model half is a
                         # SUBSTRING test and the line used to read like an equality; a bank written
                         # before the field existed simply prints the figures, as it always did.
                         "detail": f"temperature observed {', '.join(_sp['temperature_observed'])} "
                                   f"against a declared {_sp['temperature_declared']} (exact); "
                                   f"billed model {', '.join(_sp['model_observed'])} against a "
                                   f"declared {_sp['seat_declared']}"
                                   + (f" -- {_sp['model_test']}" if _sp.get("model_test") else ""),
                         "rows": []})
        if l2.get("aborted_on_cost"):
            bars.append({"bar": "L2 COST BREAKER (the run completed inside the hard cap)",
                         "verdict": "STOP",
                         "detail": f"the running total ${l2.get('running_usd', 0.0):.4f} passed the "
                                   f"${float(l2.get('cap_usd') or HARD_CAP_USD):.2f} cap mid-run; the "
                                   f"remaining rows are UNSCORED and every rate above is over a "
                                   f"truncated population",
                         "rows": []})
    lat = doc.get("latency")
    if lat:
        bars.append({"bar": f"D10 ADDED WALL p90 <= {lat['bar']['budget_ms']:.0f} ms",
                     "verdict": lat["bar"]["verdict"],
                     "detail": f"{lat['bar']['measured_ms']} ms added per turn at p90 "
                               f"(the resolver's own wall is "
                               f"{lat['ms_board_subject_ms']['p90']} ms at p90)",
                     "rows": []})
    return bars


def verdict_of(bars: list) -> tuple:
    """{LAND-DARK, STOP} and nothing else (D9). A FATAL bar STOPs; a rate bar that MISSes is reported
    by name and does not on its own STOP -- phase A's own held-out run missed two rate bars by a row
    each and landed dark under this same vocabulary. STOP is reserved for a bar whose failure means
    the wiring must not be armed at all."""
    stops = [b["bar"] for b in bars if b["verdict"] == "STOP"]
    misses = [b["bar"] for b in bars if b["verdict"] == "MISS"]
    return ("STOP" if stops else "LAND-DARK"), stops, misses


# ── THE IN-TREE BANK: the phrase-free filter and the IMMUTABLE per-run record ────────────────────
def phrase_free(block: dict) -> dict:
    """THE ONE PRODUCER OF THE IN-TREE FORM of a layer block -- counts and verdicts, never a map back
    into a deck.

    The rule is `test_pb11`'s and it is stated over KEYS rather than over substrings: a held-out row
    id beside its class and its verdict is a map back into a deck that must stay outside the tree, so
    every per-class `*_ids` list, the `unscored` row list and `group_detail` (the same map wearing a
    different key -- one entry per near_duplicate/multi row, each carrying that row's id) are dropped,
    and `shipped_carry`'s own row lists go with them by their `_rows` suffix.

    THE COUNT SURVIVES WHERE THE LIST DOES NOT. `unscored` is the field that tells a later reader
    whether a population was ASKED, and dropping it outright left the bank unable to distinguish "no
    row went unscored" from "the list was filtered": `unscored_n` is that count, and it is a number
    about rows rather than a list of them. It is ONE function because the summary, the per-run record
    and the banked markdown all have to apply the same rule -- a filter written twice is a filter that
    drifts once.

    A STATED DEVIATION, AND THE RULING THAT CLOSED IT. The design decision that created the per-run
    record said it carries "per-row picks by row id". This filter drops every `*_ids` list, `unscored`
    and `group_detail` -- the estate's id-free bank law and `test_pb11` -- so the per-row picks land
    ONLY in the scratchpad artifact's `layer2_rows`. The gate reads nothing this filter drops, so the
    certificate is whole either way, and for the HELD-OUT run the fence is the right one: a held-out
    row id in the tree is the map the deck exists to keep out. The open half was that THE SCRATCHPAD
    IS SESSION-TEMP, so after the one-shot the per-row picks would have existed in no durable place at
    all.

    RULED 2026-09-11, BOTH HALVES: the tracked bank KEEPS this fence -- phrase-free and id-free, per-
    row lists dropped -- and the FULL artifact is copied, unfiltered, to a durable UNTRACKED home
    (`--full-artifact-dir`, `docs/private/subject_heldout/`, which is gitignored), together with the
    held-out deck itself. So the per-row picks outlive the session and no held-out row id enters the
    repository, which were never in tension: they only looked it while the scratchpad was the sole
    copy. `main` refuses a `--full-artifact-dir` inside this repo that git does not call ignored.

    AND THE ARTIFACT IS ID-KEYED, NOT PHRASE-BEARING -- measured: neither `layer1_rows` nor
    `layer2_rows` carries the deck's `phrase`, so what this filter actually removes from the bank is
    the ROW ID, the join back into a deck that stays outside the tree. The durable copy is complete
    only beside that deck, which is why they share one untracked home."""
    _DROP = ("unscored", "group_detail")
    out = {k: v for k, v in block.items() if k != "per_class"}
    if isinstance(out.get("shipped_carry"), dict):
        out["shipped_carry"] = {k: v for k, v in out["shipped_carry"].items()
                                if not k.endswith("_rows")}
    per: dict = {}
    for cl, d in (block.get("per_class") or {}).items():
        if not isinstance(d, dict):
            per[cl] = d
            continue
        row = {k: v for k, v in d.items() if not k.endswith("_ids") and k not in _DROP}
        if isinstance(d.get("unscored"), list):
            row["unscored_n"] = len(d["unscored"])
        per[cl] = row
    out["per_class"] = per
    return out


def certifying_census() -> dict | None:
    """THE CERTIFYING DECK'S OWN CLASS CENSUS, READ OFF THE DECK FILE -- the gate's denominators.

    THEY USED TO COME FROM THE RECORD BEING GRADED, which made "all 91 non-decoy rows were SCORED" an
    assertion about whatever census the document happened to carry. That is a free-standing number: a
    doc naming the TRUE v3 rows digest beside a forged `class_counts` of 28 decoys and 90 non-decoy
    rows satisfied checks 3, 4 and 5 with figures the deck does not contain. The denominators are
    therefore read HERE, from `configs/graphrag/<CERTIFYING_DECK>` parsed by the same `load_deck` the
    run used, and they are trusted only when that file's rows digest is still the pinned one -- so a
    deck edited after the pre-registration yields NO denominators rather than new ones.

    None means the gate has no denominators, which is fail-closed: every check stated over them fails,
    and the readout says the deck could not be read as the pinned instrument."""
    try:
        path = _REPO / "configs" / "graphrag" / CERTIFYING_DECK
        deck = load_deck(path)
        ident = deck_identity(path, deck)
        if ident["deck_rows_sha256"] != CERTIFYING_DECK_ROWS_SHA256:
            return None
        return {"deck": ident["deck"], "deck_rows_sha256": ident["deck_rows_sha256"],
                "rows_total": len(deck["rows"]),
                "class_counts": dict(collections.Counter(r["klass"] for r in deck["rows"]))}
    # `SystemExit` IS NAMED BESIDE `Exception` AND IT IS NOT DECORATION: `load_deck` REFUSES a deck
    # with no rows, an unknown class or a phrase-less row by raising `SystemExit`, which does not
    # inherit from `Exception` -- so a malformed certifying deck would have escaped this handler and
    # taken the grading function down instead of holding the gate. A gate must fail closed even when
    # its own instrument is broken.
    except (Exception, SystemExit):   # noqa: BLE001 -- an unreadable deck yields NO denominators
        return None


def runner_provenance() -> dict:
    """WHICH CODE PRODUCED A RECORD. `runner_sha256` is this file's own bytes and is always
    resolvable; `runner_git_sha` is the tree's HEAD and is present only when git answers.

    BOTH, BECAUSE NEITHER IS THE OTHER. The runner is typically UNCOMMITTED while a wave is being
    measured -- HEAD names the tree the run was made in and says nothing about the script that made
    it, and the file digest names the script exactly and says nothing about the tree. `git rev-parse`
    is a READ: no ref moves, no index is touched, and a failure is an absent key rather than a
    raise."""
    out = {"runner_sha256": hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()}
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(_REPO),
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and r.stdout.strip():
            out["runner_git_sha"] = r.stdout.strip()
    except Exception:            # noqa: BLE001 -- a tree with no git is a missing field, never a raise
        pass
    return out


def layer2_record(doc: dict) -> dict:
    """THE IMMUTABLE PER-RUN LAYER-2 DOCUMENT: provenance, the measurement, the bars and the gate that
    was computed over THIS SAME document -- one file, written once, never merged into.

    WHY IT EXISTS. The dated `<deck>_summary.json` is a FIXED path per deck per date and it MERGES, so
    that a free layer-1 re-run cannot erase a billed layer 2. The merge preserved the layer and let the
    later run's top-level fields overwrite the provenance beside it -- MEASURED on a doctored bank,
    free: one ordinary `--layer 1` pass left an earlier layer 2 and an earlier OPEN gate sitting under
    a fresh block sha, a fresh graph hash and a fresh stamp, with the gate's own provenance checks
    asserting on the durable artifact exactly what they exist to prevent. The same site replaced a
    first calibration with a second outright, so the tree kept the LAST attempt and no count of them.
    A record that carries provenance WITH the measurement it describes cannot be transplanted, and a
    path that carries the run's own stamp cannot be clobbered; the number of attempts is then simply
    the length of the summary's pointer list.

    EVERY FIELD IS THE RUN'S OWN AND NONE IS RE-READ FROM THIS TREE. A missing field stays missing --
    filling one in from the live module at record time is the very transplant this record exists to
    stop, and the gate is fail-closed on absence, so a doc that did not record something HOLDS the
    one-shot instead of borrowing an answer.

    IT IS PHRASE-FREE AND ID-FREE BY CONSTRUCTION (:func:`phrase_free`): the record lands in the tree,
    the held-out deck's rows must not, and the per-row picks stay in the scratchpad artifact whose
    `layer2_rows` carry them. Nothing the gate reads is dropped by that filter -- what is banked is
    exactly what is graded."""
    prov = {k: doc.get(k) for k in
            ("generated_utc", "planner_block_sha256", "graph_hash", "deck", "deck_sha256",
             "deck_rows_sha256", "rows_total", "class_counts", "draws", "seat", "temperature",
             "max_contracts", "vocab_status", "own_structure_fence", "live_ids_count",
             "all_ids_count", "rescored_from")}
    prov = {k: v for k, v in prov.items() if v is not None}
    # THE DECK'S VERSION AS A FIELD OF ITS OWN, because the calibration deck is superseded and never
    # edited: v1, v2 and v3 are three instruments and a reader of one record should not have to parse
    # a filename to learn which one it names.
    _name = str(doc.get("deck") or "")
    for _part in _name.replace(".yaml", "").split("_"):
        if _part[:1] == "v" and _part[1:].isdigit():
            prov["deck_version"] = _part
    prov.update(runner_provenance())
    l2 = doc.get("layer2") or {}
    rec = {"kind": RECORD_KIND,
           "record": ("ONE LAYER-2 RUN, WRITTEN ONCE AND NEVER MERGED INTO. Provenance rides the "
                      "measurement it describes; the gate below was computed over this document. "
                      "The dated <deck>_summary.json beside it is an INDEX of these files and "
                      "certifies nothing."),
           "provenance": prov,
           # AN EMPTY LAYER 2 STAYS EMPTY. `phrase_free({})` returns `{"per_class": {}}`, which is a
           # TRUTHY dict, and the gate's "a gate that was never measured is never reported as open"
           # rule is stated over the falsiness of this field: a record for a run that made no draw
           # must be gradable as nothing at all, not as an empty measurement.
           "layer2": (phrase_free(l2) if isinstance(l2, dict) and l2 else {}),
           "bars": [{k: v for k, v in b.items() if k != "rows"} for b in (doc.get("bars") or [])],
           "verdict": doc.get("verdict"), "failing_bars": list(doc.get("failing_bars") or [])}
    if doc.get("instrument"):
        rec["instrument"] = doc["instrument"]
    return rec


def _write_new(path: Path, text: str, *, what: str) -> Path:
    """WRITE A FILE THAT DOES NOT EXIST YET, OR REFUSE -- the `open(..., "x")` rule, in one place.

    Every artifact this script produces is named for the run that made it, so an existing name means
    ANOTHER RUN'S BYTES are sitting there and a `write_text` would replace them without a word. The
    per-run record has refused a collision since the record existed; the SCRATCHPAD artifact did not,
    and the record's own refusal text cites it ("the run's own full artifact is in the scratchpad and
    nothing was lost"). A fence that another fence's honesty depends on has to hold.

    THE REFUSAL SAYS WHAT IT COST, because it costs something. The earlier file stands unmodified and
    THIS run's copy of `what` was not written; on a billed run that is a measurement whose per-row
    detail is gone, so the text says so plainly rather than reading as a tidy no-op. It fires only when
    two runs of one deck land in one directory inside one UTC second, and the remedy is a directory of
    this run's own."""
    try:
        with path.open("x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError:
        print(f"REFUSED: {path} already exists and is NOT being overwritten. That file is an earlier "
              f"run's and it stands unmodified; {what} for THIS run was not written, and this run "
              f"has banked nothing -- no record, no summary, no pointer -- because the refusal is "
              f"ahead of every one of those writes. Two runs of one deck landed in one directory "
              f"inside one UTC second: re-run with a directory of this run's own (--out-dir, or "
              f"--full-artifact-dir).")
        raise SystemExit(2) from None
    return path


def record_file_name(tag: str, record: dict) -> str:
    """THE RECORD'S NAME, DERIVED FROM THE STAMP INSIDE IT, WITHOUT WRITING ANYTHING.

    It is a function of its own because the name is needed BEFORE the write: the summary's pointer
    entry names the file, the pointer rides the summary, and the summary's prose half is rendered
    before either half of anything is written. A name computed twice in two places is a name that
    drifts once, and the gate's FILE NAME check is stated over exactly this derivation.

    AN UNSTAMPED RECORD IS REFUSED HERE rather than at the write, so the refusal still lands before a
    rendering pass that would otherwise run first and waste nothing but confusion."""
    stamp = str((record.get("provenance") or {}).get("generated_utc") or "")
    if not stamp:
        raise SystemExit("REFUSED: a per-run layer-2 record with no `generated_utc` has no name of "
                         "its own -- it would have to share a fixed path, which is the clobber this "
                         "file exists to close.")
    return f"{tag}_layer2_{stamp}.json"


def write_layer2_record(bank_dir: Path, tag: str, record: dict, *, payload: str = "") -> Path:
    """WRITE THE RECORD ONCE, AT A PATH THAT CARRIES ITS OWN STAMP, AND REFUSE TO OVERWRITE ONE.

    The refusal is the whole point and it is not decoration: the defect this closes is a later run
    silently replacing an earlier measurement at a fixed path, so a writer that would clobber MUST
    stop rather than choose. Nothing is lost when it fires -- the run's full stamped artifact is
    already on disk in the scratchpad, with every draw in it -- and the collision itself is the
    finding: two layer-2 runs of one deck stamped in the same second.

    `open(..., "x")` is the fence rather than the `exists()` test above it; the test is there so the
    refusal can name the path it refused.

    `payload` IS THE BYTES THE CALLER ALREADY HASHED. The summary's pointer carries a `record_sha256`
    and it has to be the digest of what actually lands here, so `main` serialises ONCE, hashes that
    string, and hands it back -- re-serialising at the write would make the pointer a digest of a
    document nobody can prove is this one. An omitted `payload` serialises here, which is the path
    every caller but `main` takes."""
    name = record_file_name(tag, record)
    stamp = name.split("_layer2_", 1)[1][: -len(".json")]
    path = Path(bank_dir) / name
    if path.exists():
        print(f"REFUSED: {path} already exists. A per-run layer-2 record is written ONCE and is "
              f"never merged into or overwritten -- two runs stamped {stamp} would otherwise leave "
              f"one measurement wearing the other's provenance. The run's own full artifact is in "
              f"the scratchpad and nothing was lost; bank this run under its own --bank-dir.")
        raise SystemExit(2)
    with path.open("x", encoding="utf-8", newline="\n") as fh:
        fh.write(payload or json.dumps(record, indent=2, ensure_ascii=False))
    return path


def record_pointer(record: dict, file_name: str, *, record_sha256: str = "") -> dict:
    """ONE ENTRY OF THE SUMMARY'S `layer2_runs` LIST -- what a reader needs to tell two attempts apart
    WITHOUT opening either file, and never enough to be mistaken for the certificate itself. Every
    field is a copy of the record's own, and the file name rides first so the pointer always says
    which document the verdict beside it was computed on.

    AND A DIGEST OF THE RECORD'S BYTES, WHICH IS THE ONE FIELD THAT IS NOT A COPY. Every other field
    here is restated from inside the record, so a record hand-edited IN PLACE, at its own name, moved
    the pointer's meaning with it and nothing in the tree disagreed: the gate's FILE NAME check binds
    a name to a stamp and its `graded_file_sha256` only REPORTS the bytes it read -- neither can say
    those bytes are the ones the pointer was written for. `record_sha256` is that witness, and it is
    the digest of exactly the string `write_layer2_record` puts on disk. `--grade-record` reads it
    back and refuses a mismatch by name.

    IT CORROBORATES; IT DOES NOT CERTIFY. The summary is a merged index the gate refuses by artifact
    class, so this digest can never become a fifteenth check -- it is a second witness to the same
    bytes, kept in a different file, and a pointer written before the field existed is reported as
    NOT CROSS-CHECKED rather than as a pass."""
    prov = record.get("provenance") or {}
    l2 = record.get("layer2") or {}
    gate = record.get("oneshot_gate") or {}
    return {"file": file_name,
            **({"record_sha256": record_sha256} if record_sha256 else {}),
            "generated_utc": prov.get("generated_utc"),
            "planner_block_sha256": prov.get("planner_block_sha256"),
            "graph_hash": prov.get("graph_hash"),
            "deck_rows_sha256": prov.get("deck_rows_sha256"),
            "draws": prov.get("draws"), "rows_total": prov.get("rows_total"),
            "calls": l2.get("calls"), "errored_calls": l2.get("errored_calls"),
            "usd_measured": l2.get("usd_measured"),
            "gate_verdict": gate.get("verdict") or "not graded"}


# ── the held-out one-shot gate ───────────────────────────────────────────────────────────────────
def _count(v) -> int | None:
    """A COUNT, OR None WHEN THE FIELD IS NOT ONE. `int(x or 0)` read a MISSING key, a null and a
    string alike as zero, and on a gate every one of those is a different claim: the reading that
    matters is "this document recorded a number", and anything else is an absence. `bool` is excluded
    deliberately -- `True` is an `int` in Python and it is not a census."""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _as_record(obj) -> tuple:
    """(the document, why it is NOT a per-run record or None). The gate's first check is stated over
    this: a verdict is a statement about ONE run, and the artifact that carries a run is the immutable
    per-run record -- not the merged summary beside it, whose top-level provenance names the LATEST
    run on that deck and date, and not a run doc held in memory by something that is not this
    runner."""
    if isinstance(obj, (str, Path)):
        p = Path(obj)
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:   # noqa: BLE001 -- an unreadable path is a refusal, never a pass
            return {}, f"{p.name} could not be read as a per-run record ({type(e).__name__})"
    if not isinstance(obj, dict):
        return {}, "the object handed to the gate is not a JSON document"
    if obj.get("kind") == RECORD_KIND:
        return obj, None
    if obj.get("kind") == SUMMARY_KIND or "layer2_runs" in obj:
        return obj, ("a MERGED DECK SUMMARY -- the dated bank's INDEX of runs, whose top-level "
                     "provenance names the latest run on this deck and date and not the layer 2 "
                     "beneath it; read the file its `layer2_runs` pointer names")
    return obj, (f"not a per-run layer-2 record: no `kind` of {RECORD_KIND}. A bank written before "
                 f"the record existed, or a run document, carries its provenance beside the "
                 f"measurement rather than inside it")


def oneshot_gate(record) -> dict | None:
    """THE PRE-REGISTERED GATE FOR SPENDING THE ONE-SHOT, GRADED IN CODE. Returns None when layer 2
    did not run -- a gate that was never measured is never reported as open.

    WHY THIS IS A FUNCTION AND NOT A PARAGRAPH AN OPERATOR READS. The gate is stated over the layer-2
    fields NAMED BELOW and the run's EXIT CODE is stated over every bar on the run, and on
    the calibration decks those two disagree by construction: the layer-1 decoy carry (dc23) is FATAL
    and pre-existing, the deck header authorises reading past it because the block is graded on the
    layer-2 bar, and so a run whose gate passes in full still exits 1. An operator who reads the exit
    code reads a STOP and holds a gate that opened; an operator who reads the console prose reads
    whichever line he reaches first. This reads the fields.

    WHAT IT IS HANDED. A per-run layer-2 RECORD (:func:`layer2_record`) -- as a loaded dict or as the
    path to one -- and never a merged summary, a run doc or a bank written before the record existed.
    That is check 1 and it is a check rather than an assumption because the two in-tree artifacts are
    not interchangeable: the record carries its provenance INSIDE the layer-2 document, while the
    dated summary is a fixed path that merges, so its top-level provenance names the latest run on the
    deck and date and can sit over a layer 2 made under another prompt entirely (MEASURED). Provenance
    is therefore read from `record["provenance"]` and from nowhere else.

    THE FIELDS IT IS STATED OVER, NAMED RATHER THAN COUNTED -- `layer2.per_class.decoy.{n,scored,
    fired}`, `layer2.all_non_decoy.{scored,passed}`, `layer2.errored_calls`, `layer2.seat_pin.verdict`,
    `layer2.aborted_on_cost` and the record's own `provenance.class_counts` / `rows_total`, with both
    denominators taken from THE CERTIFYING DECK FILE (:func:`certifying_census`) rather than from the
    record; and then the run's PROVENANCE, SHAPE and STANDING -- `planner_block_sha256`,
    `deck_rows_sha256`, `graph_hash`, `draws` / `rows_total` / `layer2.calls`, and `rescored_from`;
    and, when the gate is handed a PATH, the FILE NAME against the stamp inside the document.
    FOURTEEN checks, and the list is written out rather than counted because "the three fields" was
    this docstring's own wording while the function read six.

    THE NAME IS PART OF THE ARTIFACT AND NOT BESIDE IT. `write_layer2_record` derives a record's path
    FROM its `generated_utc`, so this runner can never write a file whose name disagrees with its
    stamp -- but a hand COPY can, and it did (MEASURED: `copy <deck>_layer2_20260911T110000Z.json
    <deck>_layer2_20261231T000000Z.json` graded OPEN while the readout said "computed on the per-run
    record stamped 20260911T110000Z", beside a file claiming a run that never happened). The check
    binds the two whenever there is a name to bind, and `print_gate` prints the graded file's own
    sha256 so the certificate names its BYTES and not only its stamp.

    A COUNT IS A NUMBER THIS DOCUMENT RECORDED, and every count is read as one (:func:`_count`).
    `int(x or 0)` read a missing key, a null and a string alike as zero -- which is the right verdict
    for a missing field and the wrong reading of a present one: a record whose `errored_calls` is
    `null` claimed to have a census and had none, and it passed the check that exists to grade it.

    THE CENSUS IS THE DECK'S AND NOT THE RECORD'S. `n_decoy` and `n_non_decoy` used to come from the
    document being graded, so "all 91 non-decoy rows were SCORED" asserted only that the record agreed
    with itself: a forged `class_counts` of 28 and 90 beside the TRUE v3 rows digest satisfied three
    checks with figures deck v3 does not contain. They now come from the deck file, trusted only while
    its rows digest is the pinned one, and the record's own census is graded AGAINST it and required
    to sum to its own `rows_total`.

    OUTCOMES ARE HALF A GATE. The checks above grade WHAT HAPPENED and none of them graded WHAT
    RAN, and five runs satisfied every one of them while measuring something the gate was not
    pre-registered over:
      THE PROMPT. Every deck header states that a run whose block sha is not the stamped one is
        measuring a different text and its decoy figures do not carry across -- and the gate never read
        the sha. A bank carrying the block's v2 text (37900160...) with an otherwise clean layer 2
        opened a gate certifying v3. Every run has RECORDED `planner_block_sha256` since the field was
        added; THE PROMPT check is the first thing to READ it, against the live pin rather than
        against a constant, so the certificate is "these draws were made under the prompt this tree
        ships". AND THE RECORDED SIDE IS NOW A MEASUREMENT: `main` renders `dispatch._subject_block`
        over the run's own `live_ids(graph)` and hashes it, refusing before any spend on a mismatch.
        Until 2026-09-11 it wrote the module CONSTANT and :func:`live_block_sha` read the SAME
        constant back, so this check was a constant against itself at both ends -- MEASURED, a
        `_subject_block` rendering a different text still recorded the pin and the gate read OPEN on
        354 clean calls. The pin stays the comparand, which is what makes the check bite on a LATER
        reading of the record.
      THE DECK. `n_decoy` and `n_non_decoy` were read from the doc's OWN `class_counts`, which made
        them an assertion about the deck that ran and not about the deck the gate was written for: a
        clean run on v2 (28 decoys, 90 non-decoy) is internally consistent and it OPENED. v2 and v3
        differ by one row, so THE DECK is stated over a digest of the rows and not over the filename
        -- and the denominators themselves now come from the deck FILE (see above).
      THE GRAPH, which is the third input and the one neither of the other two can stand in for. The
        pinned block is substitution-free -- MEASURED, `_subject_block(('a',))` and
        `_subject_block(('El_Nino',))` are the same text -- so its sha names the PROMPT and carries
        none of the enum the prompt is asked over. What the planner may pick is `live_ids(graph)` =
        `all_ids(graph)` MINUS `OWN_STRUCTURE_IDS`: `graph_hash` is the field that names the graph
        half, and the fence half is a module constant RECORDED on the record (`own_structure_fence`,
        `live_ids_count`) rather than graded, because at record time it is read from the same process
        that made the draws. A doc carrying a stale hash, a stale `vocab_status` and a four-month-old
        `generated_utc` opened the gate with zero failing checks. THE GRAPH compares it to the LIVE
        hash and never to a constant: the deck is frozen for the certification, the graph is meant to
        move between sittings.
      THE SHAPE. The layer-2 bars are stated at ">= 2 of 3 draws" and the decoy bar at "ZERO picks on
        ANY draw". A `--draws 1` run has no 2-of-3 reading at all and its counts are all consistent;
        THE SHAPE requires the pre-registered three draws AND `calls == rows x draws`, so a population
        that was scored but never fully asked cannot read as a whole one.
      THE MEASUREMENT ITSELF. A `--rescore` re-reads banked picks under whatever scorer stands today,
        and on a clean v3 bank every other check passes -- only the DECK check's `measured` string
        named it, so the readout told and the gate did not grade. THE MEASUREMENT reads `rescored_from`
        (and the decoration `--rescore` puts on the deck label, for a doc written before that field),
        so the gate opens on the run that made the draws and not on a re-read of it.

    THE LAST THREE ARE SELF-COMPARISONS ON A LIVE RUN AND THAT IS NOT A WEAKNESS -- it is where they
    bite. On the run that writes the record, `planner_block_sha256` and `graph_hash` are read from the
    same process a moment before the comparison, so they cannot fail; what they grade is every LATER
    reading of that record -- a bank re-graded tomorrow, a `--rescore`, a document produced by
    something other than this runner -- and that is exactly the population the one-shot's operator
    reads from. A check that can only fail on a foreign or stale document is a check about foreign and
    stale documents. WHAT CHANGED ON 2026-09-11 is that the live run's own side is now a MEASUREMENT
    and not a restatement: `planner_block_sha256` is the digest of the block text `main` rendered, and
    the run REFUSES outright when that digest is not the pin -- so the live-run guarantee is made by
    the fence, before any spend, and the check is left to do the job it is good at.

    IT IS FAIL-CLOSED IN EVERY DIRECTION. A missing decoy class, a decoy census at zero, a missing
    seat pin, a population the cost breaker truncated, one unscored row, an ABSENT provenance field,
    an absent deck digest, an absent graph hash, an absent call census -- each is a FAILED check and
    none of them is a silent pass. The scored count is graded against the DECK's own class census
    rather than against a constant, so a deck whose rows moved cannot satisfy a gate written for
    another one; and the decoy denominator must be POSITIVE, so a deck with no decoys in it cannot
    satisfy the FATAL decoy bar vacuously.

    AND THE DECOY SIDE IS GUARDED THE SAME WAY THE NON-DECOY SIDE ALWAYS WAS. `fired` is computed
    over the non-errored draws alone, so a decoy row whose every draw raised reads as "did not fire".
    Before this, twenty-seven such rows read `{n: 27, fired: 0}` and the gate OPENED on a run that
    billed eighty-one errored calls and measured nothing -- the exact fail-open shape the non-decoy
    `scored == n` check exists to stop. So the decoy check now requires every decoy row SCORED, and a
    sixth check requires `errored_calls == 0` across the whole run: the one-shot is spent on a clean
    measurement or it is not spent.

    THE VOCABULARY IS ITS OWN. D9 fixes the run verdict to {LAND-DARK, STOP} and this script cannot
    widen it; the gate is a different question asked of the same run, so it answers in {OPEN, HELD}
    and never touches the run's `verdict`. A document of the wrong artifact class is REFUSED inside
    that vocabulary rather than beside it: the refusal is check 1, it FAILS, and the verdict is HELD --
    a third word would be a third thing for an operator to interpret at the seat."""
    _named_path = isinstance(record, (str, Path))
    # THE BYTES THE VERDICT IS ABOUT, NAMED. A certificate that says only "stamped 20260911T110000Z"
    # names a RUN and not a FILE, and a hand-copy puts a file in the tree named for a run that did not
    # happen (MEASURED: `copy <a>_layer2_...110000Z.json <a>_layer2_...20261231T000000Z.json` graded
    # OPEN, and the readout said "computed on the per-run record stamped 20260911T110000Z" beside a
    # file claiming another run). The name check below closes the name; this digest closes the bytes.
    _file_name = Path(record).name if _named_path else None
    _file_sha = None
    if _named_path:
        try:
            _file_sha = hashlib.sha256(Path(record).read_bytes()).hexdigest()
        except Exception:    # noqa: BLE001 -- unreadable bytes are refused by CLASS, below, not here
            _file_sha = None
    rec, wrong_class = _as_record(record)
    l2 = rec.get("layer2") if isinstance(rec.get("layer2"), dict) else {}
    _is_summary = rec.get("kind") == SUMMARY_KIND or "layer2_runs" in rec
    if not l2 and not _is_summary and not _named_path and rec.get("kind") != RECORD_KIND:
        # A GATE THAT WAS NEVER MEASURED IS NEVER REPORTED AS OPEN -- and a document with no layer 2
        # in it, no run index and no record kind either is not an artifact this gate has anything to
        # say about.
        # A NAMED PATH IS ONE EXCEPTION AND IT IS ALWAYS ANSWERED: an operator who hands this function
        # a file has asked a question about that file, and silence would read as "no gate here" when
        # the truth is "that path could not be read as one".
        # A PER-RUN RECORD IS THE OTHER, AND IT CLOSES AN ASYMMETRY. A document carrying
        # `kind: subject_resolver_layer2_run_v1` with an EMPTY `layer2` used to answer HELD from a
        # path and None from a dict -- the same document, two readings, and a caller taking None for
        # "nothing to grade" would have missed "this RECORD recorded no measurement". A record is
        # answered in the same words whichever door it arrives through; the verdict is HELD, on the
        # measurement checks, and never OPEN. Silence is the answer to a doc with nothing in it, never
        # to a name and never to a record.
        return None
    prov = rec.get("provenance") if isinstance(rec.get("provenance"), dict) else {}
    dec = (l2.get("per_class") or {}).get("decoy") or {}
    agg = l2.get("all_non_decoy") or {}
    pin = l2.get("seat_pin") or {}
    # THE DENOMINATORS COME FROM THE DECK FILE, NOT FROM THE DOCUMENT BEING GRADED. See
    # :func:`certifying_census`: a census carried by the record is a number the record agrees with
    # itself about, and a forged one beside a TRUE rows digest opened three checks.
    _census = certifying_census()
    _rec_counts = prov.get("class_counts") if isinstance(prov.get("class_counts"), dict) else None
    _rows_total = _count(prov.get("rows_total"))
    _deck_is_certifying = bool(_census) and prov.get("deck_rows_sha256") == _census["deck_rows_sha256"]
    if _deck_is_certifying:
        n_decoy = int(_census["class_counts"].get("decoy") or 0)
        n_non_decoy = sum(int(v) for k, v in _census["class_counts"].items() if k != "decoy")
    else:
        n_decoy = n_non_decoy = 0                     # no denominators: fail-closed, never a pass
    # EVERY COUNT IS READ AS A COUNT (:func:`_count`): a present-but-null field is an ABSENCE and not a
    # zero, which is the difference between "this run recorded no errors" and "this run recorded
    # nothing".
    scored, passed = _count(agg.get("scored")), _count(agg.get("passed"))
    fired = _count(dec.get("fired"))
    # THE DECOY SIDE'S OWN scored/n, READ THE WAY THE NON-DECOY SIDE'S ALWAYS WAS. A decoy row whose
    # every draw errored is not a decoy that declined: `fired` never saw it. `scored` is absent from
    # a bank written before this check existed, and the check below requires a COUNT and not merely
    # the key -- fail-closed, which is the only safe reading for a field that decides whether the
    # one-shot is spent.
    dec_n, dec_scored = _count(dec.get("n")), _count(dec.get("scored"))
    calls, errored = _count(l2.get("calls")), _count(l2.get("errored_calls"))
    # THE RUN'S IDENTITY, beside its outcomes: which PROMPT the draws were made under, which DECK was
    # measured, and whether the run had the SHAPE the bars are stated over. Each is read from the
    # RECORD'S OWN PROVENANCE and compared to this tree, and each reads as ABSENT rather than as zero
    # -- a bank written before a field existed fails the check that field is for instead of skipping
    # it.
    got_block, live_block = prov.get("planner_block_sha256"), live_block_sha()
    got_deck, got_rows_sha = prov.get("deck"), prov.get("deck_rows_sha256")
    got_graph, live_graph = prov.get("graph_hash"), live_graph_hash_or_none()
    draws, rows_total = _count(prov.get("draws")), _rows_total
    shape_known = (draws is not None and draws > 0 and rows_total is not None and rows_total > 0
                   and calls is not None)
    # AND WHETHER THIS DOC IS A RUN OR A RE-READ OF ONE. `--rescore` writes both of these: the
    # structural field is what the check is stated over, and the decoration on the deck label is read
    # beside it so that a doc produced before the field existed is still recognised. Absence of both
    # means "a run", which is the normal case and the only one that may open the gate.
    rescored = prov.get("rescored_from") or ("(RE-SCORED" in str(got_deck or ""))
    _census_sum = (sum(v for v in _rec_counts.values() if isinstance(v, int))
                   if _rec_counts and all(isinstance(v, int) and not isinstance(v, bool)
                                          for v in _rec_counts.values()) else None)
    # THE DENOMINATOR IN THE CHECK'S OWN NAME. When the certifying deck cannot be read -- or this
    # record is not that deck's -- there IS no denominator, and printing the zero the arithmetic uses
    # would put "0 of 0 fired ... and all 0 SCORED" on the console beside a FAIL: the sentence a
    # vacuous pass would print. `?` says the thing that is true, and the `measured` column says why.
    _dn = n_decoy if _deck_is_certifying else "?"
    _nn = n_non_decoy if _deck_is_certifying else "?"
    # ── THE NAME AGAINST THE STAMP INSIDE THE FILE. `write_layer2_record` derives the name FROM the
    #    record's `generated_utc`, so the runner itself can never write a file whose name disagrees
    #    with its stamp -- but a COPY can, and the operator's door to this gate is a path. When the
    #    gate is handed a dict there is no name to disagree with anything and the check passes saying
    #    so; when it is handed a path the two must bind, and a record with no stamp at all has nothing
    #    to bind its name to and FAILS.
    _want_name = (f"_layer2_{prov['generated_utc']}.json"
                  if isinstance(prov.get("generated_utc"), str) and prov.get("generated_utc")
                  else None)
    _name_ok = (True if not _named_path
                else bool(_want_name) and str(_file_name).endswith(_want_name))
    checks = [
        # ── WHAT THE GATE WAS HANDED. Everything below is a statement about ONE run, and only one
        #    artifact carries one run: the immutable per-run record, whose provenance sits INSIDE the
        #    layer-2 document. The merged summary is an index, a run doc is a thing in memory, and a
        #    bank written before the record existed carries provenance that a later run can overwrite.
        {"check": "THE ARTIFACT CLASS: a per-run layer-2 record, not a summary or a run doc",
         "measured": ("a per-run layer-2 record" if wrong_class is None
                      else f"REFUSED -- {wrong_class}"),
         "pass": wrong_class is None},
        # ── AND THE NAME IT WEARS, bound to the stamp it carries. The runner derives one from the
        #    other, so this can only fail on a file somebody moved, copied or renamed -- which is
        #    precisely the population an operator hands to `--grade-record`.
        # ── WHAT IT CHECKS, SAID IN THE CHECK'S OWN WORDS: a SUFFIX. The name must END in
        #    `_layer2_<the stamp inside>.json` and the text before that is not graded here at all --
        #    a record copied to `anything_layer2_<its own stamp>.json` passes this and is meant to.
        #    IDENTITY IS BOUND BY THE ROWS DIGEST (`THE DECK`, check 11) and by the block sha and the
        #    graph hash beside it, none of which a file name can carry; this check closes ONE hole,
        #    which is a file NAMED for a run whose stamp it does not hold. Saying "carries the stamp"
        #    without saying "as a suffix" invited the opposite reading -- that the name is the
        #    record's identity -- and a reader who believes that reads a filename as provenance.
        {"check": "THE FILE NAME: the name ENDS in the stamp of the run inside it (a suffix test; "
                  "identity is bound by THE DECK's rows digest, not by a name)",
         "measured": ("graded on a document held in memory -- it has no file name to disagree with "
                      "its stamp, and the runner derives one from the other"
                      if not _named_path
                      else f"{_file_name} ends in '{_want_name}', the stamp it carries"
                      if _name_ok
                      else f"{_file_name} does not end in '{_want_name}' -- it is NAMED for a run it "
                           f"does not carry" if _want_name
                      else f"{_file_name} names a document with no generated_utc to bind it to"),
         "pass": _name_ok},
        # ── THE DECK'S OWN CENSUS, AND THE RECORD GRADED AGAINST IT rather than against itself.
        {"check": "THE CENSUS: the record's classes are the certifying deck's, and they sum to it",
         "measured": (f"the certifying deck {CERTIFYING_DECK} could not be read at its pinned rows "
                      f"digest -- the gate has no denominators" if not _census
                      else f"this record names deck rows "
                           f"{str(got_rows_sha or 'none')[:12]}, not the certifying "
                           f"{_census['deck_rows_sha256'][:12]}" if not _deck_is_certifying
                      else "the record carries no class census" if _rec_counts is None
                      else f"{_census_sum} rows in {len(_rec_counts)} classes against the deck file's "
                           f"{_census['rows_total']} ({n_decoy} decoy / {n_non_decoy} non-decoy); the "
                           f"record's own rows_total is {rows_total}"),
         "pass": (_deck_is_certifying and _rec_counts is not None and _census_sum is not None
                  and _rec_counts == _census["class_counts"]
                  and rows_total is not None and _census_sum == rows_total == _census["rows_total"])},
        {"check": f"DECOYS: 0 of {_dn} fired on ANY draw, and all {_dn} SCORED",
         # THE ABSENCE OF A CENSUS IS PRINTED AS AN ABSENCE. Reading a missing key as zero is the right
         # reading for the verdict (fail-closed) and the wrong one for the readout: a bank written
         # before the field existed printed "0 of 27 scored", which is the console line of a run that
         # asked nothing -- a different and far worse failure than the one that actually occurred.
         "measured": ("the deck's decoy class was not scored" if not dec
                      else f"{fired} fired; {dec_scored} of {dec_n} scored"
                      if fired is not None and dec_scored is not None
                      else f"{fired} fired; the run recorded no scored census for the decoy class"
                      if fired is not None
                      else "the run recorded no decoy fire census"),
         # AND THE DENOMINATOR MUST BE POSITIVE. At zero the whole line reads "0 of 0 fired ... and all
         # 0 SCORED -- PASS": a FATAL bar satisfied by a deck with no decoys in it. Unreachable now
         # that the denominator is the pinned deck file's, and the guard stays because the check must
         # be true of the arithmetic and not of the caller.
         "pass": bool(dec) and n_decoy > 0 and fired == 0 and dec_n == n_decoy
                 and dec_scored == n_decoy},
        {"check": f"NON-DECOY: all {_nn} of the deck's rows were SCORED",
         "measured": (f"{scored} scored" if scored is not None
                      else "the run recorded no non-decoy scored census"),
         "pass": n_non_decoy > 0 and scored == n_non_decoy},
        {"check": "NON-DECOY: every scored row PASSED",
         "measured": (f"{passed} of {scored} passed" if scored is not None and passed is not None
                      else "the run recorded no non-decoy pass census"),
         "pass": scored is not None and scored > 0 and passed == scored},
        # THE WHOLE RUN, NOT A CLASS. The two `scored` checks above are per-population; a draw that
        # errored on a row whose other two draws landed is invisible to both, and it still means the
        # gate is reading a 2-draw row as a 3-draw one. Zero is the bar; a bank with no `errored_calls`
        # key AND a bank whose `errored_calls` is null both fail it rather than skipping it.
        {"check": "EVERY DRAW WAS SCORED: no call errored anywhere on the run",
         "measured": (f"{errored} of {calls} calls errored" if errored is not None
                      else "the run recorded no errored-call census"),
         "pass": errored == 0},
        # THE SEAT PIN AS THE SCORER GRADED IT, AND THE READOUT SAYS WHAT THAT GRADING IS. The model
        # half is a SUBSTRING test -- the declared seat must appear inside every billed model id --
        # because a provider prefix or a dated suffix is the same seat and a different family is not.
        # An operator reading "PASS" is entitled to know which question passed.
        {"check": "SEAT PIN: temperature exact, model FAMILY by substring, read back from every draw",
         "measured": (str(pin.get("verdict") or "no seat pin was recorded")
                      + (f" ({pin['model_test']})" if pin.get("model_test") else "")),
         "pass": pin.get("verdict") == "PASS"},
        {"check": "THE POPULATION IS WHOLE: the run completed inside its own cap",
         "measured": ("the cost breaker truncated the run" if l2.get("aborted_on_cost")
                      else "ran to the last row"),
         "pass": not l2.get("aborted_on_cost")},
        # ── AND THE FIVE THAT GRADE WHAT RAN RATHER THAN WHAT HAPPENED ──────────────────────────
        # The digests are compared in FULL and printed at twelve characters, which is the estate's own
        # idiom for a hash on a console line (the graph hash, the vocabulary hash). The full recorded
        # value rides the artifact and the bank on its own key, so the comparison is auditable off the
        # file without trusting the readout's width.
        {"check": "PROVENANCE: the draws were made under the LIVE planner block",
         "measured": (f"{got_block[:12]} against the live {live_block[:12]}"
                      if got_block and live_block
                      else "the run recorded no planner block sha" if not got_block
                      else f"{got_block[:12]}; the live block sha could not be read"),
         "pass": bool(got_block) and bool(live_block) and got_block == live_block},
        {"check": f"THE DECK: the rows measured are {CERTIFYING_DECK}'s",
         "measured": (f"{got_deck or 'an unnamed deck'} rows {got_rows_sha[:12]} against the "
                      f"certifying {CERTIFYING_DECK_ROWS_SHA256[:12]}" if got_rows_sha
                      else f"{got_deck or 'an unnamed deck'} recorded no deck identity"),
         "pass": bool(got_rows_sha) and got_rows_sha == CERTIFYING_DECK_ROWS_SHA256},
        # THE GRAPH, which is the input that decides what the planner could pick AT ALL. The block sha
        # cannot stand in for it: the pinned text is substitution-free (MEASURED -- the block renders
        # identically for a one-id vocabulary and for `El_Nino`), so it names the prompt and carries
        # none of the enum. `live_ids(graph)` is `all_ids(graph)` MINUS `OWN_STRUCTURE_IDS`, so the
        # enum has two inputs: `graph_hash` is the only field on a run that names the GRAPH half, and
        # the fence half rides the record as `own_structure_fence` / `live_ids_count` (a record, not a
        # check -- at record time it is the same process that made the draws). It is compared to the
        # LIVE hash and never to a constant -- the deck is frozen for the certification, the graph is
        # meant to move between sittings, and a run made against a graph this tree no longer loads is
        # measuring a different `live_ids`. Reachable on exactly the path the provenance checks exist
        # for: a `--rescore` carries the banked `graph_hash` while re-scoring under the LIVE group
        # index, and the gate it writes is a durable "OPEN" string in the bank.
        {"check": "THE GRAPH: the draws were made against the LIVE graph",
         "measured": (f"{got_graph} against the live {live_graph}" if got_graph and live_graph
                      else "the run recorded no graph hash" if not got_graph
                      else f"{got_graph}; the live graph hash could not be read"),
         "pass": bool(got_graph) and bool(live_graph) and got_graph == live_graph},
        {"check": f"THE SHAPE: {CERTIFYING_DRAWS} draws on every row of the deck",
         "measured": (f"{draws} draws x {rows_total} rows = {calls} calls" if shape_known
                      else "the run recorded no draw, row or call census"),
         "pass": shape_known and draws == CERTIFYING_DRAWS
                 and calls == rows_total * CERTIFYING_DRAWS},
        # AND THAT THIS IS THE MEASUREMENT AND NOT A RE-READ OF ONE. The gate is pre-registered over a
        # RUN -- the draws, the scorer and the group index that stood when the money was spent. A
        # `--rescore` re-reads banked picks under whatever scorer stands today, and on a clean v3 bank
        # every other check passes: only the DECK check's `measured` string named it, so the readout
        # told and the gate did not grade. A re-score remains a first-class $0 diagnostic -- it prints
        # its bars, its fence and this gate's own reasons -- it simply cannot be the thing the one-shot
        # is spent on.
        {"check": "THE MEASUREMENT: the gate is graded on the run that made the draws",
         "measured": (f"a RE-SCORE of {prov.get('rescored_from') or 'a banked run'} -- a re-read of "
                      f"banked picks under today's scorer, not the run it would certify"
                      if rescored else "a run, not a re-score"),
         "pass": not rescored},
    ]
    return {"gate": "HELD-OUT ONE-SHOT -- pre-registered as 'a clean calibration decoy bar'",
            "certifies": (prov.get("generated_utc") or "an unstamped document"),
            # WHICH BYTES, beside which stamp. Present only when the gate was handed a PATH: a
            # document graded in memory has no file to name, and inventing one would be the same
            # class of claim this whole arc exists to stop.
            **({"graded_file": _file_name} if _named_path else {}),
            **({"graded_file_sha256": _file_sha} if _file_sha else {}),
            "checks": checks,
            "failing": [c["check"] for c in checks if not c["pass"]],
            "verdict": "OPEN" if all(c["pass"] for c in checks) else "HELD"}


def crosscheck_pointer(path: Path, gate: dict) -> tuple[list[str], bool | None]:
    """(the readout lines, the verdict) -- THE RECORD PUT BACK AGAINST THE INDEX WRITTEN BESIDE IT.

    `True` agrees, `None` could not be checked, `False` DISAGREES and is a refusal.

    WHY A SECOND WITNESS EXISTS AT ALL. Every one of the gate's fourteen checks is computed from
    fields INSIDE the document it is handed, so a record edited in place -- at its own name, keeping
    its own stamp -- moves the evidence and the verdict together and no check can see it. MEASURED,
    free: a banked run whose gate HELD on one fired decoy, hand-edited at its own path to read zero,
    graded OPEN with fourteen of fourteen and printed a sha256 of the doctored bytes as if that were
    corroboration. The summary's pointer is the only record of what the bytes were when the pointer
    was written, and it lives in a different file.

    IT REFUSES RATHER THAN GRADES, and the distinction is the whole design. The summary is a MERGED
    index the gate refuses to certify by artifact class (check 1), so this can never become a
    fifteenth check -- it cannot make a HELD record open. It can only stop an operator spending a
    one-shot on a document its own index disagrees with.

    A VERDICT DISAGREEMENT IS A REFUSAL TOO, and not only a sha one. The pointer's `gate_verdict` is
    what the fourteen checks said when the money was spent; a different answer today means the tree
    around the record moved -- the graph, the pinned block, or the certifying deck -- and the gate
    read now is not the gate that was pre-registered over that run. The safe direction is already
    safe (OPEN then, HELD now, exits 1 and spends nothing); this closes the other one.

    ABSENCE IS NEVER A PASS AND NEVER A REFUSAL: no sibling summary, or a pointer written before
    `record_sha256` existed, reports NOT CROSS-CHECKED in as many words."""
    name = path.name
    if "_layer2_" not in name:
        return ([f"  -- NOT CROSS-CHECKED: {name} is not named like a per-run record "
                 f"(<deck>_layer2_<stamp>.json), so there is no sibling summary to look for."], None)
    sib = path.parent / f"{name.split('_layer2_', 1)[0]}_summary.json"
    if not sib.is_file():
        return ([f"  -- NOT CROSS-CHECKED: no {sib.name} beside this record. The pointer list is the "
                 f"only second witness to a record's bytes and this directory has none."], None)
    try:
        doc = json.loads(sib.read_text(encoding="utf-8"))
    except Exception as e:          # noqa: BLE001 -- an unreadable index is an absence, not a lie
        return ([f"  -- NOT CROSS-CHECKED: {sib.name} could not be read "
                 f"({type(e).__name__})."], None)
    ptr = next((r for r in (doc.get("layer2_runs") or [])
                if isinstance(r, dict) and r.get("file") == name), None)
    if ptr is None:
        # NOT A REFUSAL, AND DELIBERATELY SO. This cross-check asks whether a record still holds the
        # bytes ITS OWN pointer was written for; a file the index does not name has no pointer to
        # disagree with, and the instrument for a record that arrived here by COPY is the gate's own
        # FILE NAME check (2), which binds the name to the stamp inside. Refusing here would answer a
        # question with exit 2 that check (2) already answers with a graded FAIL.
        return ([f"  -- NOT CROSS-CHECKED: {sib.name} is this directory's index of layer-2 runs and "
                 f"its `layer2_runs` list does not name {name}, so there is no pointer to compare "
                 f"against. A record that arrived by copy is graded by THE FILE NAME check above."],
                None)
    lines, verdict = [], True
    want = ptr.get("record_sha256")
    got = None
    try:
        got = hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:               # noqa: BLE001 -- unreadable bytes are refused by CLASS, not here
        pass
    if not want:
        lines.append(f"  -- `record_sha256`: NOT CROSS-CHECKED -- the pointer in {sib.name} carries "
                     f"no digest (written before the field existed).")
    elif want == got:
        lines.append(f"  -- `record_sha256` agrees with {sib.name}: {want}")
    else:
        verdict = False
        lines.append(f"  -- REFUSED on `record_sha256`: {sib.name} was written for bytes hashing "
                     f"{want}, and this file's bytes hash {got or '(unreadable)'}. The record was "
                     f"changed after its pointer was written -- at its own name and its own stamp, "
                     f"which is the one edit no check inside the document can see.")
    _pv, _gv = ptr.get("gate_verdict"), gate.get("verdict")
    if not _pv or _pv == "not graded":
        lines.append("  -- `gate_verdict`: NOT CROSS-CHECKED -- the pointer records none.")
    elif _pv == _gv:
        lines.append(f"  -- `gate_verdict` agrees with {sib.name}: {_pv} then, {_gv} now")
    else:
        verdict = False
        lines.append(f"  -- REFUSED on `gate_verdict`: {sib.name} recorded {_pv} when this record "
                     f"was banked and the same fourteen checks read {_gv} today. The document did "
                     f"not move (or the digest above would say so), so the tree around it did -- the "
                     f"graph, the pinned block, or the certifying deck -- and the gate read now is "
                     f"not the gate pre-registered over that run.")
    return (lines, verdict)


def print_gate(gate: dict) -> None:
    """THE GATE READOUT, A FUNCTION SO THAT IT CAN BE GRADED. It is the only half of this script a
    BILLED run produces that a free run never reaches -- layer 2 is where the gate comes from -- so
    inline in `main` it would have shipped to the paid seat having never once been executed. ASCII
    only, like every other line this script prints."""
    print("")
    print(f"THE HELD-OUT ONE-SHOT GATE ({_ascii(gate['gate'])})")
    print("  -- graded on the layer-2 fields plus the run's own provenance, shape and standing")
    print("     (which prompt, which deck, which GRAPH, three draws a row, a run and not a re-score,")
    print("     and the ARTIFACT itself: its class, and the name it wears against the stamp inside);")
    print("     NOT the VERDICT line above and NOT the exit code")
    # WHICH DOCUMENT THIS VERDICT IS ABOUT. The gate certifies ONE per-run record and the operator's
    # next act is to hand that file's path to the one-shot agent, so the stamp it was computed on is
    # printed with the verdict rather than left to be matched up afterwards.
    print(f"  -- computed on the per-run layer-2 record stamped {_ascii(gate.get('certifies'))}")
    # AND WHICH BYTES THAT WAS, when the gate was handed a path. A stamp names a RUN; a file name and
    # a digest name the DOCUMENT, and the two can be made to disagree by a copy (MEASURED). The name
    # is graded by its own check above; the sha is printed so the certificate says what it read.
    if gate.get("graded_file"):
        print(f"  -- the graded file is {_ascii(gate['graded_file'])}"
              + (f"  sha256 {_ascii(gate['graded_file_sha256'])}"
                 if gate.get("graded_file_sha256") else "  (its bytes could not be read)"))
    # WHOSE RUN THIS QUESTION IS ASKED OF, said on the console because the one-shot's own run will
    # print this block too. The gate is the decision to SPEND the one-shot, and it is stated over the
    # CALIBRATION deck -- so a run on any other deck (the held-out one included) holds it by
    # construction, and that reading is the fence working rather than a defect to debug at the seat.
    print(f"  -- asked of the CALIBRATION run ({_ascii(CERTIFYING_DECK)}): it is the decision to SPEND")
    print("     the one-shot, so a run on any other deck HOLDS it by construction")
    for c in gate["checks"]:
        print(f"  {'PASS' if c['pass'] else 'FAIL':<5} {_ascii(c['check']):<58} "
              f"{_ascii(c['measured'])}")
    print(f"  GATE: {gate['verdict']} -- "
          + ("every pre-registered check passed; the held-out one-shot may be run ONCE."
             if gate["verdict"] == "OPEN"
             else "failing: " + "; ".join(_ascii(x) for x in gate["failing"])
                  + ". The one-shot is NOT spent."))


# ── the call plan ────────────────────────────────────────────────────────────────────────────────
def print_plan(deck: dict, *, layer: str, draws: int, latency: bool, latency_n: int,
               cap_usd: float = HARD_CAP_USD, identity: dict | None = None,
               bank_dir: Path | None = None, tag: str = "") -> float:
    rows = deck["rows"]
    by_class = collections.Counter(r["klass"] for r in rows)
    calls = len(rows) * draws if layer in ("2", "both") else 0
    est = calls * PER_CALL_USD
    print("CALL PLAN")
    print(f"  deck        {deck_label(deck['path'])}  ({len(rows)} rows)")
    # THE PROVENANCE, PRINTED BEFORE THE MONEY AND NOT ONLY BANKED AFTER IT. These are the three
    # inputs the one-shot gate is now stated over, and the plan is the last thing an operator reads
    # before spending: "which prompt", "which deck" and "which graph" belong where the decision is
    # made. A `--dry-run` costs nothing and this is what it is for -- and the graph line matters most
    # there, because a dry run returns before the `graph ...` line the real run prints after loading.
    if identity:
        _blk = live_block_sha()
        _gph = live_graph_hash_or_none()
        _match = identity.get("deck_rows_sha256") == CERTIFYING_DECK_ROWS_SHA256
        # THE BLOCK SHA HERE IS THE PIN AND SAYS SO. The plan prints before the graph loads, so the
        # rendered block cannot be hashed yet; the run MEASURES it (dispatch._subject_block over its
        # own live_ids) a moment later and REFUSES on a mismatch, and it is the measured digest that
        # reaches the record. A dry run is entitled to know which of the two it is reading.
        print(f"  provenance  planner block {(_blk or 'UNREADABLE')[:12]} (the PIN; the run measures "
              f"the rendered block and refuses on a mismatch)")
        print(f"              graph {_gph or 'UNREADABLE'}  "
              f"deck rows {identity['deck_rows_sha256'][:12]}  "
              f"deck file {identity['deck_sha256'][:12]}")
        print(f"              the one-shot gate certifies {CERTIFYING_DECK} at rows "
              f"{CERTIFYING_DECK_ROWS_SHA256[:12]} -- this deck "
              f"{'IS' if _match else 'is NOT'} it"
              + ("" if _match else "; a run on it cannot open the gate"))
    print(f"  classes     " + "  ".join(f"{k}={by_class[k]}" for k in CLASSES if by_class[k]))
    print(f"  seat        {SEAT}  temperature={TEMPERATURE}  "
          f"max_contracts={deck['max_contracts']}  today={deck['today']}")
    print(f"  layer 1     {'RUN ' if layer in ('1', 'both') else 'skip'}  "
          f"{len(rows) if layer in ('1', 'both') else 0} deterministic scorings, 0 API calls, $0.00")
    print(f"  layer 2     {'RUN ' if layer in ('2', 'both') else 'skip'}  "
          f"{calls} plan_turn calls ({len(rows)} rows x {draws} draws)")
    print(f"  latency     {'RUN ' if latency else 'skip'}  "
          f"{min(latency_n, len(rows)) if latency else 0} phrases x 3 embeds, 0 API calls, $0.00")
    # WHAT THE BILLED HALF WILL BANK, PRINTED BEFORE THE MONEY. The per-run record is the document the
    # one-shot gate certifies and the one whose path an operator hands on by name, so a `--dry-run`
    # that costs nothing is exactly where its shape belongs -- an operator should never first meet the
    # certificate's fields in the artifact he is about to act on.
    if calls and bank_dir is not None:
        print(f"  record      {bank_dir / (tag + '_layer2_[the run stamp].json')}")
        print(f"              WRITTEN ONCE and never merged into; an existing path is REFUSED. It "
              f"carries, together:")
        print(f"                provenance  generated_utc, planner_block_sha256, graph_hash, deck, "
              f"deck_sha256,")
        print(f"                            deck_rows_sha256, deck_version, rows_total, "
              f"class_counts, draws, seat,")
        print(f"                            temperature, max_contracts, vocab_status, "
              f"own_structure_fence, live_ids_count,")
        print(f"                            all_ids_count, runner_sha256 (+ runner_git_sha where git "
              f"answers)")
        print(f"                layer2      per class n/scored/passed/fired/unscored_n, "
              f"all_non_decoy, calls, errored_calls,")
        print(f"                            usd_measured, seat_pin, cap_usd -- phrase-free and "
              f"id-free (no row list)")
        print(f"                bars        every evaluated bar, its verdict and its detail, "
              f"without the row ids")
        print("                oneshot_gate  the fourteen pre-registered checks, graded over THAT "
              "SAME document")
        print(f"              and {tag}_summary.json beside it keeps only the append-only pointer "
              f"list `layer2_runs`")
        print(f"              plus the latest verdict copied for a reader: the attempt count is the "
              f"list's length.")
        print(f"              Each pointer carries `record_sha256`, the digest of the record's bytes "
              f"as written; --grade-record")
        print(f"              puts the file back against it and REFUSES a mismatch (it corroborates "
              f"and never certifies).")
    print(f"  ESTIMATE    {calls} calls x ${PER_CALL_USD:.2f}/call (the planner's per-call anchor) "
          f"= ${est:.2f}")
    print(f"  EXPOSURE, said before and not after: the CEILING is the budget number. "
          f"{calls} calls at the anchor is ${est:.2f} against a ${cap_usd:.2f} hard cap"
          f"{'' if cap_usd == HARD_CAP_USD else f' (this run; the sitting ceiling is ${HARD_CAP_USD:.2f})'}"
          f"; the BILLED figure is read back from the usage fields and reported as measured dollars.")
    return est


# ── main ─────────────────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Subject-resolver deck runner (D9 layers 1/2 + D10)")
    # NO DEFAULT, DELIBERATELY. The deck IS the instrument; a billed run on the wrong one is money
    # spent measuring nothing, and a default is how the wrong one gets measured. The help names the
    # current deck instead, because `--help` is what an operator reads before spending.
    ap.add_argument("--deck", help="deck YAML, REQUIRED (no default). The current calibration deck "
                                   "is configs/graphrag/subject_deck_v3.yaml; v1 and v2 are frozen "
                                   "predecessors that still run and still reproduce their own "
                                   "banked figures")
    ap.add_argument("--rescore", default="",
                    help="re-score a BANKED run's draws offline under the current scorer and exit. "
                         "Spends nothing, reads no deck and makes no call: the draws are the "
                         "measurement and the scorer is the thing that moved.")
    # THE GATE, READ OFF A NAMED PATH, FOR $0 AND WITHOUT WRITING PYTHON. The one-shot is spent on a
    # FILE and the operator's instruction is to read the gate off that file by name -- so the door has
    # to be a command, or "read the gate off the record" becomes "trust the console line the run
    # printed an hour ago". It loads nothing else: no deck, no graph beyond the live hash, no call.
    ap.add_argument("--grade-record", default="",
                    help="grade the one-shot gate over a banked PER-RUN layer-2 record and exit "
                         "(0 = OPEN, 1 = HELD, 2 = not a gradable record, or the record disagrees "
                         "with the sibling summary's pointer). Spends nothing.")
    ap.add_argument("--layer", default="both", choices=("1", "2", "both", "none"),
                    help="1 = the free tiers, 2 = the billed planner, both (default), none")
    ap.add_argument("--draws", type=int, default=3, help="layer-2 draws per row (default 3)")
    ap.add_argument("--latency", action="store_true", help="run the D10 latency harness (free)")
    ap.add_argument("--latency-n", type=int, default=40, help="phrases for the latency harness")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the call plan and the dollar estimate; spend nothing")
    # THE CEILING IS AN ARGUMENT AND NOT ONLY A CONSTANT. `HARD_CAP_USD` is the SITTING's ceiling and
    # it stays the default; a single run's ceiling is often tighter (the owner's phase-E law is $4 for
    # the calibration re-run and $4 for the one-shot). Without this flag that tighter number was held
    # by the printed ESTIMATE and by the operator reading it -- a WATCHED budget. Threaded into both
    # fences below it becomes a FENCED one: the pre-flight refusal grades the estimate against it and
    # `run_layer2`'s running total breaks on it mid-run. It can only tighten, never widen: a value
    # above the sitting's own ceiling is refused.
    ap.add_argument("--cap-usd", type=float, default=HARD_CAP_USD,
                    help=f"this run's dollar ceiling (default {HARD_CAP_USD:.2f}, the sitting's; a "
                         f"value above it is refused)")
    ap.add_argument("--out-dir", default=str(SCRATCH), help="scratchpad artifact directory")
    # WHERE THE PER-ROW DETAIL LIVES AFTER THE SESSION ENDS. The in-tree bank is phrase-free and
    # id-free by law (`phrase_free`), and the scratchpad is session-temp -- so without this flag the
    # held-out one-shot's per-row picks would exist in no durable place at all, which is the open
    # question the phrase-free fence left and the owner's ruling closed: KEEP the fence, and copy the
    # full artifact to an untracked home. `docs/private/` is gitignored in this tree.
    ap.add_argument("--full-artifact-dir", default="",
                    help="ALSO copy the full artifact (every draw and every per-row pick, by ROW ID) "
                         "here, unfiltered, so it outlives the session. This directory must be "
                         "UNTRACKED -- docs/private/subject_heldout/ is the phase-E home, is "
                         "gitignored, and is where the held-out deck (the id -> ask join) lives.")
    ap.add_argument("--bank-dir", default="", help="in-tree phrase-free summary dir (default by date)")
    ap.add_argument("--no-bank", action="store_true", help="skip the in-tree summary")
    args = ap.parse_args(argv)

    # ── THE GATE OVER A NAMED RECORD. First, because it reads one file and decides one thing; and
    #    because the operator who runs it is about to spend a one-shot on what it says.
    if args.grade_record:
        _p = Path(args.grade_record)
        # THE ONLY REFUSAL HERE IS A NAME THAT IS NOT A FILE -- a typo, and the likeliest error when a
        # path is carried between two agents by hand. Everything else is ANSWERED: `oneshot_gate`
        # never returns None for a path, because a document that cannot be read as a record is a
        # REFUSED artifact class and not a silence.
        if not _p.is_file():
            print(f"REFUSED: no such record: {_p}. The gate is read off a PATH -- check the name, "
                  f"and read it off the per-run record rather than the dated summary.")
            return 2
        _g = oneshot_gate(_p)
        print(f"grading: {_p}")
        print_gate(_g)
        # ── AND THE RECORD AGAINST THE INDEX WRITTEN BESIDE IT, which is the only witness to what
        #    this file's bytes were when its pointer was written. It cannot open a held gate -- see
        #    `crosscheck_pointer` -- it can only refuse.
        _x_lines, _x_ok = crosscheck_pointer(_p, _g)
        print("")
        print("THE SIBLING SUMMARY'S POINTER (a second witness, in a different file; it corroborates "
              "and never certifies)")
        for _line in _x_lines:
            print(_ascii(_line))
        if _x_ok is False:
            print("  CROSS-CHECK: REFUSED. Do not spend the one-shot on this document.")
            return 2
        return 0 if _g["verdict"] == "OPEN" else 1

    # ── THE OFFLINE RE-SCORE. A banked run carries every draw's picks, so a scorer correction is a
    #    RE-READ of one measurement and never a second run -- the same discipline the T2 gate's
    #    decision table is recomputed under. It loads the graph (the group index is the scorer's other
    #    input and it must be the LIVE one), and it makes no API call and reads no deck.
    if args.rescore:
        src = Path(args.rescore)
        if not src.is_file():
            print(f"REFUSED: banked run not found: {src}")
            return 2
        banked = json.loads(src.read_text(encoding="utf-8"))
        rows2 = list(banked.get("layer2_rows") or [])
        if not rows2:
            print(f"REFUSED: {src} carries no layer2_rows -- there are no draws to re-score.")
            return 2
        graph = load_graph()
        of_id, inv = group_index(graph)
        sc = score_layer2(rows2, of_id=of_id, inv=inv)
        # `class_counts`, `planner_block_sha256` AND THE DECK DIGESTS ARE CARRIED FROM THE BANKED RUN,
        # and every one of them is a property of the DRAWS rather than of this process: the deck census
        # is what the one-shot gate's denominators are taken from (without it the gate cannot be graded
        # on a re-score, and a re-score is exactly when a scorer correction moves the gate), the block
        # sha names the prompt those draws were made under -- which is not necessarily the text in this
        # tree today -- and the rows digest names the deck they were drawn on. A re-score that dropped
        # them would hand the gate a doc with no provenance, and the gate is fail-closed on absence, so
        # the correction would read as a held gate rather than as a missing field.
        doc = {k: banked.get(k) for k in ("generated_utc", "deck", "rows_total", "class_counts",
                                          "graph_hash", "vocab_status", "planner_block_sha256",
                                          "deck_sha256", "deck_rows_sha256",
                                          # AND THE SEAT AND THE ENUM'S TWO HALVES, where the banked
                                          # run recorded them: every one is a property of the DRAWS
                                          # and none of this process, so a re-score that re-derived
                                          # them from today's tree would be inventing provenance for
                                          # a measurement it did not make.
                                          "seat", "temperature", "own_structure_fence",
                                          "live_ids_count", "all_ids_count",
                                          "draws", "max_contracts")}
        # A KEY ABSENT FROM AN OLDER BANK STAYS PRESENT AND None, exactly as the six carried keys
        # always have: `markdown` indexes several of these, and dropping a missing one would turn a
        # blank field into a KeyError on the first artifact written before the field existed.
        doc["deck"] = f"{banked.get('deck')} (RE-SCORED from {src.name})"
        # AND THE SAME FACT AS A FIELD RATHER THAN AS A DECORATION ON A LABEL. The one-shot gate is
        # pre-registered over a RUN, and a re-score is a re-read of banked picks under today's scorer;
        # until this was recorded the only trace of the difference was inside a `measured` string,
        # which the readout printed and the gate did not grade. See `oneshot_gate`'s last check.
        doc["rescored_from"] = src.name
        doc["layers_run"] = ["2"]
        doc["layer2"] = dict(sc, aborted_on_cost=bool((banked.get("layer2") or {})
                                                      .get("aborted_on_cost")))
        # THE FENCE, ON THE SAME BANKED DRAWS. A re-read and never a second run: it costs nothing,
        # consumes no one-shot, and its own artifact field says it is a counterfactual.
        doc["fence_rescore"] = fence_rescore(rows2, list(banked.get("layer1_rows") or []))
        doc["bars"] = collect_bars(doc)
        doc["verdict"], _stops, _misses = verdict_of(doc["bars"])
        doc["failing_bars"] = _stops + _misses
        # THE GATE IS GRADED ON A RECORD, AND A RE-SCORE BUILDS ONE RATHER THAN BEING EXEMPTED FROM
        # THE RULE. It is never BANKED as one -- a re-score made no draw and is not a run -- but it is
        # graded through the same door every measurement is, so its own readout prints the reason it
        # holds (`THE MEASUREMENT`) instead of the reason a wrong artifact class would.
        _rec = layer2_record(doc)
        _g = oneshot_gate(_rec)
        if _g:
            _rec["oneshot_gate"] = _g
            doc["oneshot_gate"] = _g
        print(_ascii(markdown(doc)))
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = _utc_stamp()
        dst = out_dir / f"{src.stem}_RESCORED_{stamp}.json"
        dst.write_text(json.dumps(dict(doc, layer2_record=_rec, layer2_rows=rows2),
                                  indent=2, ensure_ascii=False),
                       encoding="utf-8", newline="\n")
        print(f"artifact: {dst}")
        # THE RE-SCORE ANSWERS WITH ITS OWN VERDICT, the way `main`'s tail does. It returned 0
        # UNCONDITIONALLY -- a $0 diagnostic whose exit code could not fail, which is the estate's
        # "READ EVERY EXIT CODE" law from the other side: DRIVEN on a bank whose re-score printed
        # `## THE HELD-OUT ONE-SHOT GATE -- HELD` and its own STOP bar, and exited 0. `--grade-record`
        # already answers 0/1/2 and this path follows the run it re-read: 1 when a bar STOPs.
        # (The GATE is still not the exit code here either -- a re-score can never open it, and the
        # readout says so under `THE MEASUREMENT`.)
        return 1 if doc["verdict"] == "STOP" else 0

    # ── THE DURABLE HOME MUST BE UNTRACKED, AND THAT IS FENCED BEFORE ANYTHING IS READ OR SPENT.
    #    `--full-artifact-dir` writes the UNFILTERED artifact: every draw and every per-row pick,
    #    keyed by ROW ID. The row id is the map into the deck -- it is exactly what `phrase_free`
    #    drops from the tracked bank -- so on a held-out run these are the bytes the phrase-free
    #    regime exists to keep out of the repository, and "point it somewhere untracked" is an
    #    instruction, not a fence. A path inside this repo is therefore put to `git check-ignore` --
    #    a READ, no ref moves, no index is touched -- and anything git does not positively call
    #    IGNORED is REFUSED. A path outside the repo is outside the question. Fail-closed on git's
    #    silence: unprovable is not proven.
    if args.full_artifact_dir:
        _fa_probe = (Path(args.full_artifact_dir) / "artifact.json").resolve()
        _inside = str(_fa_probe).lower().startswith(str(_REPO.resolve()).lower() + os.sep)
        if _inside:
            _ci = 1
            try:
                _ci = subprocess.run(["git", "check-ignore", "-q", str(_fa_probe)], cwd=str(_REPO),
                                     capture_output=True, text=True, timeout=20).returncode
            except Exception:        # noqa: BLE001 -- a tree with no git cannot prove it, so REFUSE
                _ci = 1
            if _ci != 0:
                print(f"REFUSED: --full-artifact-dir {args.full_artifact_dir} is inside this "
                      f"repository and git does not report it as IGNORED. That directory would "
                      f"receive the UNFILTERED artifact -- every draw and every per-row pick, keyed "
                      f"by ROW ID, which is the map into the deck that the in-tree bank drops by law. "
                      f"Nothing was read, nothing was spent. Point it at an untracked home: "
                      f"docs/private/subject_heldout/ is gitignored here.")
                return 2

    if not args.deck:
        print("REFUSED: --deck is required (or --rescore a banked run).")
        return 2
    deck_path = Path(args.deck)
    if not deck_path.exists():
        print(f"REFUSED: deck not found: {deck_path}")
        return 2
    deck = load_deck(deck_path)
    # WHICH DECK THIS RUN IS ABOUT TO MEASURE, computed ONCE from the file that was actually read and
    # threaded into the plan, the artifact and the bank. See :func:`deck_identity`: the gate's deck
    # check is stated over `deck_rows_sha256` because a name is not an identity.
    ident = deck_identity(deck_path, deck)
    if args.draws < 1:
        print("REFUSED: --draws must be >= 1")
        return 2
    if args.layer == "none" and not args.latency:
        print("REFUSED: nothing to run (--layer none and no --latency)")
        return 2

    if args.cap_usd > HARD_CAP_USD:
        print(f"REFUSED: --cap-usd ${args.cap_usd:.2f} is above the sitting's own "
              f"${HARD_CAP_USD:.2f} ceiling. The flag TIGHTENS a run's budget; it never widens it.")
        return 2
    if args.cap_usd <= 0:
        print("REFUSED: --cap-usd must be positive.")
        return 2
    # THE BANK DIRECTORY IS RESOLVED ONCE, BEFORE THE PLAN PRINTS IT. A path an operator reads in the
    # dry run and a path the run writes to must be the same string or the dry run is a different
    # question; the date is UTC and the same for both.
    bank_dir = Path(args.bank_dir) if args.bank_dir else (
        BANK / _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d"))
    est = print_plan(deck, layer=args.layer, draws=args.draws, latency=args.latency,
                     latency_n=args.latency_n, cap_usd=args.cap_usd, identity=ident,
                     bank_dir=(None if args.no_bank else bank_dir), tag=deck_path.stem)
    if args.dry_run:
        print("DRY RUN: no API call made, nothing spent.")
        return 0
    if est > args.cap_usd:
        print(f"REFUSED: the estimate ${est:.2f} exceeds this run's ${args.cap_usd:.2f} cap"
              f"{'' if args.cap_usd == HARD_CAP_USD else f' (the sitting ceiling is ${HARD_CAP_USD:.2f})'}.")
        return 2
    if args.layer in ("2", "both"):
        if os.environ.get("GRAPHRAG_DISPATCH", "llm") == "rules":
            print("REFUSED: GRAPHRAG_DISPATCH=rules -- every row would fall back (vacuous run).")
            return 2
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("REFUSED: ANTHROPIC_API_KEY is not set in this environment.")
            return 2

    from leviathan.graphrag.state import subject as SU
    t0 = time.perf_counter()
    graph = load_graph()
    vocab, vstatus = SU.load_vocab(graph=graph)
    # THE ENUM'S SIZE AND THE FENCE'S, TOGETHER. `live_ids` is what the planner is offered and
    # `all_ids` is what the tiers match over, so a reader of this header can tell a curation change
    # (both numbers move) from a fence change (only the first does) without opening the module.
    _lint = SU.own_structure_candidates(graph)
    print(f"graph {SU.live_graph_hash(graph)}  contracts {len(graph.contracts)}  "
          f"driver ids {len(SU.live_ids(graph))} of {len(SU.all_ids(graph))}  "
          f"own-structure fence {sorted(SU.OWN_STRUCTURE_IDS)} "
          f"(lint unfenced: {list(_lint['unfenced']) or 'none'})  "
          f"artifact {vstatus}  ({time.perf_counter() - t0:.1f}s)")
    # THE ARTIFACT FENCE (the FILE). The INSTRUMENT fence -- whether the tier actually ran, which is a
    # different failure and the one that reproduced in this checkout -- is below, after layer 1.
    # `--latency` is fenced here too: a harness that times a declining tier times the free tiers.
    if (args.layer in ("1", "2", "both") or args.latency) and vstatus != "ok":
        print(f"REFUSED: the vocabulary artifact is '{vstatus}' -- the semantic tier would decline and "
              f"a run would measure the two free tiers while reporting three.")
        return 2
    # ── THE PROMPT, MEASURED AND NOT DECLARED, AND FENCED BEFORE A CENT IS SPENT.
    #    THE DEFECT THIS CLOSES. `doc["planner_block_sha256"]` was `SU.SUBJECT_BLOCK_SHA256`, the
    #    module CONSTANT, and `live_block_sha()` read the SAME constant back -- so the gate's
    #    PROVENANCE check ("the draws were made under the LIVE planner block") was a constant against
    #    itself at both ends, and nothing anywhere in this runner hashed the block text the run
    #    actually sends. MEASURED, free and in-process: with `dispatch._subject_block` returning a text
    #    hashing to 14703c0a77c8 while the pin stayed d7ed2de860fc, the run RECORDED d7ed2de860fc, the
    #    readout printed "PASS  PROVENANCE ... d7ed2de860fc against the live d7ed2de860fc", and the
    #    GATE read OPEN with zero failing checks on 354 clean calls. That is the exact fail-open this
    #    arc closed for THE DECK (hashed off the file) and THE GRAPH (stamped off the DAG bytes),
    #    sitting under the certificate's headline claim.
    #    THE FIX IS TO MEASURE THE THING. The block is rendered HERE with this run's own enum --
    #    `live_ids(graph)`, the tuple `orchestrator.py` threads into `plan_turn` -- and hashed. The
    #    digest is what the record carries, so `planner_block_sha256` becomes a reading of the prompt
    #    rather than a restatement of the pin. A mismatch REFUSES: nothing billed, nothing banked,
    #    because a run under a text this tree does not ship is money spent measuring a prompt nobody
    #    will serve, and every deck header says such a run's decoy figures do not carry across.
    #    `config_check` clause (2) and `pb16`/`pe7` grade the live render too -- but neither runs
    #    inside a calibration, and this arc's rule is that the gate reads the FIELDS rather than
    #    trusting that something else was run first.
    try:
        # `_dsp` and not `_dp`: the instrument-dead branch below already binds `_dp` to a diagnostic
        # PATH, and two meanings for one name in one function is a trap whatever the scopes allow.
        from leviathan.graphrag import dispatch as _dsp
        _live_ids = tuple(SU.live_ids(graph))
        measured_block_sha = hashlib.sha256(
            _dsp._subject_block(_live_ids).encode("utf-8")).hexdigest()
    except Exception as e:      # noqa: BLE001 -- a prompt that cannot be rendered is a REFUSAL
        print(f"REFUSED: the planner's subject block could not be RENDERED "
              f"({type(e).__name__}: {_ascii(e)}) -- a run that cannot read the prompt it is about "
              f"to send cannot record which prompt it measured. Nothing was banked or spent.")
        return 2
    print(f"prompt block {measured_block_sha[:12]}  MEASURED from dispatch._subject_block over this "
          f"run's own {len(_live_ids)} ids, against the pin {SU.SUBJECT_BLOCK_SHA256[:12]}")
    if measured_block_sha != SU.SUBJECT_BLOCK_SHA256:
        print("")
        print(f"REFUSED: THE PROMPT THIS RUN WOULD SEND IS NOT THE PROMPT THIS TREE PINS. "
              f"dispatch._subject_block renders a text hashing to {measured_block_sha}; "
              f"state.subject.SUBJECT_BLOCK_SHA256 is {SU.SUBJECT_BLOCK_SHA256}.")
        print("         Every deck header states that a run whose block sha is not the stamped one "
              "is measuring a DIFFERENT TEXT and its decoy figures do not carry across. NOTHING WAS "
              "BANKED, no call was made and nothing was spent.")
        print("         Either the block was edited -- which VOIDS the freeze and CONSUMES the "
              "held-out set -- or the pin is stale. Re-freeze deliberately (config_check clause "
              "(2) grades the same render), never in passing.")
        return 2
    of_id, inv = group_index(graph)

    doc: dict = {"generated_utc": _utc_stamp(),
                 # `deck`, `deck_path`, `deck_sha256`, `deck_rows_sha256` -- WHICH INSTRUMENT this run
                 # measured, from the one producer. The gate's deck check reads the rows digest; the
                 # path stays out of the bank (it is the only one of the four that can name where a
                 # held-out deck lives).
                 **ident,
                 "rows_total": len(deck["rows"]),
                 "class_counts": dict(collections.Counter(r["klass"] for r in deck["rows"])),
                 "graph_hash": SU.live_graph_hash(graph), "vocab_status": vstatus,
                 # WHICH PROMPT THIS RUN MEASURED -- the digest MEASURED off the rendered block a few
                 # lines above, never the module constant. Every deck header says in as many words
                 # that a run whose block sha is not the stamped one is measuring a different text and
                 # its decoy figures do not carry across; recording the CONSTANT made that claim
                 # unfalsifiable on both sides of the gate's provenance check (MEASURED -- see the
                 # fence above). Recording the MEASUREMENT makes the field a reading of the prompt,
                 # and the fence above is what guarantees a banked run was made under the pin.
                 "planner_block_sha256": measured_block_sha,
                 # AND THE OTHER HALF OF THE ENUM. `live_ids(graph)` is `all_ids(graph)` MINUS
                 # `OWN_STRUCTURE_IDS`, so the graph hash above names one input and the fence names
                 # the other: a curation change moves both counts, a fence change moves only the
                 # first, and a reader of a bank can tell them apart without opening the module. Both
                 # are RECORDS rather than checks -- they are read from the same process that made the
                 # draws -- and both are phrase-free (a driver id is not a deck row).
                 "own_structure_fence": sorted(SU.OWN_STRUCTURE_IDS),
                 "live_ids_count": len(SU.live_ids(graph)),
                 "all_ids_count": len(SU.all_ids(graph)),
                 "seat": SEAT, "temperature": TEMPERATURE, "draws": args.draws,
                 "max_contracts": deck["max_contracts"], "layers_run": []}

    l1_scored: list = []
    rows2: list = []
    l2_meta: dict = {}
    if args.layer in ("1", "2", "both"):
        print("[layer 1] the deterministic tiers"
              if args.layer in ("1", "both")
              else "[layer 1] (required to build the hint lines layer 2 sends)")
        l1_scored = layer1_rows(deck["rows"], graph=graph, vocab=vocab)
        # ── THE INSTRUMENT FENCE. Read `instrument_census` for what this is protecting against; the
        #    short form is that `load_vocab` grades the FILE and the EMBEDDER is a different failure,
        #    so an `artifact: ok` header is NOT evidence the semantic tier ran. This refuses BEFORE
        #    layer 2 spends and BEFORE anything is banked -- a non-certifying run must never leave a
        #    summary in `data/subject_resolver/` that a later reader takes for a measurement.
        doc["instrument"] = instrument_census(l1_scored)
        _inst = doc["instrument"]
        print(f"instrument: {'LIVE' if _inst['live'] else 'DEAD'}  "
              f"per-row vocab_status {_inst['census']}")
        if not _inst["live"]:
            _calls = len(deck["rows"]) * args.draws if args.layer in ("2", "both") else 0
            print("")
            print(f"REFUSED: THE INSTRUMENT IS DEAD, NOT THE DECK. The semantic tier declined on "
                  f"{_inst['declined_rows']} of {_inst['rows_scanned']} rows ({_inst['declined']}) while the "
                  f"artifact loaded '{vstatus}' -- load_vocab grades the FILE and the embedder is a "
                  f"different failure.")
            print(f"         A run scored in this state measures two tiers while reporting three: "
                  f"every class lands at its lexical floor and the report's own header still reads "
                  f"'artifact: {vstatus}'.")
            if _calls:
                print(f"         Layer 2 would have BILLED {_calls} planner calls on a hint line that "
                      f"is the empty string, and on the held-out deck that spends a ONE-SHOT set.")
            print(f"         NOTHING WAS BANKED and no call was made. Diagnose the embedder "
                  f"(leviathan.graphrag.evidence.embed), then re-run.")
            _diag = Path(args.out_dir)
            _diag.mkdir(parents=True, exist_ok=True)
            _dp = _diag / (f"{deck_path.stem}_"
                           f"{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
                           f"_REFUSED_instrument_dead.json")
            _dp.write_text(json.dumps(dict(doc, certifying=False, layer1_rows=l1_scored),
                                      indent=2, ensure_ascii=False),
                           encoding="utf-8", newline="\n")
            print(f"diagnostic (NOT a measurement): {_dp}")
            return 2
        if args.layer in ("1", "both"):
            doc["layer1"] = score_layer1(l1_scored, of_id=of_id, inv=inv)
            # THE SECOND READING OF THE CARRY, beside the bar's own and never in place of it.
            doc["layer1"]["shipped_carry"] = shipped_carry(l1_scored, of_id=of_id)
            doc["layers_run"].append("1")
    if args.layer in ("2", "both"):
        print("[layer 2] the planner")
        from leviathan.graphrag import answer as an
        rows2 = run_layer2(deck["rows"], graph=graph,
                           l1_by_id={r["id"]: r for r in l1_scored}, draws=args.draws,
                           max_contracts=deck["max_contracts"], today=deck["today"],
                           inner_call=an._call_opus, meta=l2_meta, cap_usd=args.cap_usd)
        doc["layer2"] = score_layer2(rows2, of_id=of_id, inv=inv)
        doc["layer2"]["aborted_on_cost"] = bool(l2_meta.get("aborted"))
        doc["layer2"]["running_usd"] = round(float(l2_meta.get("spent") or 0.0), 4)
        # THE CAP THIS RUN ACTUALLY RAN UNDER, banked beside the total it is graded against. The
        # breaker's bar quotes it; without the field a tightened run would print the SITTING's ceiling
        # and misstate the number the run was actually stopped by.
        doc["layer2"]["cap_usd"] = float(args.cap_usd)
        doc["layers_run"].append("2")
    if args.latency:
        print("[D10] the latency harness")
        doc["latency"] = run_latency(deck["rows"], graph=graph, n=args.latency_n)
        doc["layers_run"].append("latency")

    doc["bars"] = collect_bars(doc)
    doc["verdict"], stops, misses = verdict_of(doc["bars"])
    doc["failing_bars"] = stops + misses
    # ── THE PER-RUN RECORD, AND THE GATE COMPUTED OVER IT. The record is built FIRST and the gate is
    #    graded on that document rather than on `doc`, so the thing certified and the thing banked are
    #    the same bytes: a verdict computed over one shape and written beside another is how a
    #    certificate stops being about the measurement under it.
    record = layer2_record(doc) if doc.get("layer2") else None
    _gate = oneshot_gate(record) if record is not None else None
    if _gate:
        record["oneshot_gate"] = _gate
        doc["oneshot_gate"] = _gate

    # ── the artifacts. The SCRATCHPAD copy carries per-row detail; the IN-TREE bank carries class
    #    counts and nothing else -- no phrase, no row id, no expected id, so a held-out deck's rows
    #    cannot reach the tree through this path.
    stamp = _utc_stamp()
    tag = deck_path.stem
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # THE RECORD'S NAME IS KNOWN BEFORE IT IS WRITTEN -- it is the deck's tag and the run's own stamp
    # and nothing else -- so the report can name the file it certifies without the write having to
    # happen first. `--no-bank` leaves the key absent, which is true: there is no in-tree record.
    # ONE PRODUCER OF THE NAME (`record_file_name`), here and at the pointer and at the write: the
    # gate's FILE NAME check is stated over that derivation, and a second copy of it in this function
    # is a name that drifts once and a check that passes on the wrong file.
    if record is not None and not args.no_bank:
        doc["layer2_record_file"] = record_file_name(tag, record)
    full = dict(doc)
    if record is not None:
        full["layer2_record"] = record
    if l1_scored:
        full["layer1_rows"] = l1_scored
    if doc.get("layer2"):
        full["layer2_rows"] = rows2
    # THE PROSE HALF IS RENDERED BEFORE EITHER HALF IS WRITTEN. `markdown` reads a dozen fields off a
    # document it did not build, and when it raised the JSON was already on disk: a report that does
    # not exist beside a bank that does is two halves that disagree, and the JSON is the half a reader
    # trusts. Rendering first makes a rendering failure lose BOTH halves, which is the honest outcome.
    _md = markdown(doc)
    # LF, EXPLICITLY, ON EVERY ARTIFACT THIS SCRIPT WRITES. `write_text` translates "\n" to the
    # platform's line ending, and the estate's tracked text is LF on every platform -- a
    # Windows-authored bank would otherwise land CRLF in a repository whose every other data artifact
    # is LF, and the diff would be the whole file.
    # AND `x`, NOT `w`, BECAUSE THE RECORD'S OWN REFUSAL CITES THIS FILE. `write_layer2_record`
    # declines a stamp collision with the words "the run's own full artifact is in the scratchpad and
    # nothing was lost" -- a claim this site made false while it wrote with `write_text`, which
    # overwrites. The scratchpad copy is the ONLY place the per-row picks and the held-out phrases
    # ever live, so it is the last file in this script that may be silently replaced.
    _write_new(out_dir / f"{tag}_{stamp}.json", json.dumps(full, indent=2, ensure_ascii=False),
               what="the run's full artifact (every draw, every pick)")
    _write_new(out_dir / f"{tag}_{stamp}.md", _md, what="the run's report")
    print(f"artifact: {out_dir / (tag + '_' + stamp + '.json')}")
    # ── AND A DURABLE COPY OF THAT ARTIFACT, WHERE THE OWNER ASKED FOR ONE. The scratchpad is
    #    session-temp: after the held-out one-shot the per-row picks would exist nowhere that outlives
    #    the session, and the in-tree bank is phrase-free and id-free by law and always will be. So
    #    the full artifact is COPIED, unfiltered, to an untracked home named on the command line --
    #    for phase E, `docs/private/subject_heldout/` (gitignored), which is where the DECK that keys
    #    these rows lives -- the artifact is id-keyed and carries no ask, so the two are durable
    #    together or not at all. It is a copy and never a move: the scratchpad original stays exactly
    #    where the console says it is.
    if args.full_artifact_dir:
        _fa = Path(args.full_artifact_dir)
        _fa.mkdir(parents=True, exist_ok=True)
        for _suffix, _text in ((".json", json.dumps(full, indent=2, ensure_ascii=False)),
                               (".md", _md)):
            _write_new(_fa / f"{tag}_{stamp}{_suffix}", _text,
                       what="the DURABLE copy of the run's full artifact")
        print(f"durable:  {_fa / (tag + '_' + stamp + '.json')}  (every draw and every per-row pick, "
              f"by ROW ID; UNTRACKED by design -- never commit this directory, and keep the deck "
              f"that keys it in the same place)")

    if not args.no_bank:
        bank_dir.mkdir(parents=True, exist_ok=True)
        # THE WHITELIST IS THE FILTER, and the three digests join it deliberately: a hex digest carries
        # no phrase and no row id, and the in-tree bank is exactly where "which prompt did these
        # figures measure" and "which deck were they measured on" are asked, months later, by a reader
        # with no scratchpad. `deck_path` stays OUT -- it is the one identity field that could name
        # where a held-out deck lives.
        summary = {k: doc[k] for k in ("generated_utc", "deck", "rows_total", "class_counts",
                                       "graph_hash", "vocab_status", "planner_block_sha256",
                                       "deck_sha256", "deck_rows_sha256",
                                       "own_structure_fence", "live_ids_count", "all_ids_count",
                                       "seat", "temperature",
                                       "draws", "max_contracts", "layers_run", "verdict",
                                       "failing_bars") if k in doc}
        # THE SUMMARY SAYS WHAT IT IS. It is a FIXED path per deck per date and it MERGES, so its
        # top-level fields name the LATEST run on this deck and date; the gate reads that word and
        # refuses to certify this document, which is the whole reason the word is written.
        summary["kind"] = SUMMARY_KIND
        # THE INSTRUMENT CENSUS RIDES THE BANK. It is a count of status WORDS over rows -- no phrase,
        # no row id -- and it is what tells a later reader that the semantic tier was alive when these
        # figures were taken. A bank without it is a bank whose floors cannot be distinguished from a
        # dead embedder's.
        if doc.get("instrument"):
            summary["instrument"] = doc["instrument"]
        # THE BARS LOSE THEIR ROW LISTS HERE. Counts and verdicts are the measurement; the row ids are
        # the map back into a deck that must stay outside the tree.
        summary["bars"] = [{k: v for k, v in b.items() if k != "rows"} for b in doc["bars"]]
        # LAYER 1 RIDES THE SUMMARY; LAYER 2 DOES NOT, AND THAT IS THE FIX. The free layer runs often
        # and its figures are re-derivable at will, so a merged path is the right home for them. The
        # BILLED layer is a measurement that cost money and can never be re-derived, and the merge is
        # exactly what transplanted a later run's provenance onto it -- so it lives in its own
        # immutable per-run record and the summary keeps a POINTER to that file. `phrase_free` is the
        # one producer of the in-tree form for both (see the function: `*_ids`, `unscored` and
        # `group_detail` are the map back into a deck that must stay outside the tree).
        if doc.get("layer1"):
            summary["layer1"] = phrase_free(doc["layer1"])
        if doc.get("latency"):
            summary["latency"] = doc["latency"]              # already phrase-free: percentiles only
        # ── THE IMMUTABLE PER-RUN RECORD'S NAME, ITS BYTES AND ITS DIGEST -- COMPUTED HERE, WRITTEN
        #    BELOW, AFTER THE SUMMARY'S PROSE HALF HAS RENDERED. The write used to sit at this line,
        #    and that put the one artifact the one-shot is spent against OUTSIDE the render-before-
        #    write rule every other artifact in this function obeys. MEASURED, end to end and free:
        #    a layer-2 run into a copy of the real `data/subject_resolver/2026-09-10` bank raised
        #    `KeyError: 'passed_shipped_v1'` inside `markdown(summary)` -- the legacy layer-2 block the
        #    merge carries -- with the record ALREADY on disk and the pointer entry never written. The
        #    tree kept a record no index named, the summary's two halves stayed at the predecessor's
        #    run, and the attempt count read zero on two attempts. The KeyError is closed above; the
        #    ORDER is what makes that class of failure lose all three halves together instead of
        #    banking one of them.
        #    The name is derivable without the write (`record_file_name`), so the pointer can be built
        #    and rendered first; the bytes are serialised ONCE so the digest in the pointer is the
        #    digest of what lands.
        _pointer = None
        _rec_payload = ""
        _rec_name = ""
        if record is not None:
            _rec_name = record_file_name(tag, record)
            _rec_payload = json.dumps(record, indent=2, ensure_ascii=False)
            _pointer = record_pointer(
                record, _rec_name,
                record_sha256=hashlib.sha256(_rec_payload.encode("utf-8")).hexdigest())
        # THE DATED SUMMARY IS CUMULATIVE, NEVER CLOBBERING. Two runs of the same deck on the same date
        # measure different layers (layer 1 is free and runs often; layer 2 is billed and runs once),
        # and a plain write would silently replace a banked layer-1 result with a later re-run -- the
        # reader would see a deck whose earlier measurement had vanished with no error. An existing
        # summary for the same deck is READ and the new run's layers are merged onto it, with
        # `layers_run` the union in canonical order and `layer2_runs` APPENDED to in order.
        _prev_path = bank_dir / f"{tag}_summary.json"
        if _prev_path.is_file():
            try:
                _prev = json.loads(_prev_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 -- an unreadable predecessor is replaced, not merged
                _prev = {}
            if isinstance(_prev, dict):
                _merged = dict(_prev)
                _merged.update(summary)
                _merged["layers_run"] = [x for x in ("1", "2", "latency")
                                         if x in set(_prev.get("layers_run") or [])
                                         | set(summary.get("layers_run") or [])]
                for _k in ("layer1", "layer2", "latency"):     # a layer this run did not measure
                    _stamp_k = f"{_k}_generated_utc"
                    if _k not in summary and _k in _prev:      # keeps its banked figures
                        # A `layer2` BLOCK ON A PREDECESSOR IS A LEGACY SHAPE, from before the per-run
                        # record existed. It is CARRIED and never deleted -- it is somebody's banked
                        # figures -- and it can no longer certify anything: the gate's first check
                        # refuses this whole document by its artifact class.
                        _merged[_k] = _prev[_k]
                        # AND A CARRIED BLOCK IS STAMPED WITH THE RUN THAT MEASURED IT. `update` above
                        # replaces the header's `generated_utc`, `planner_block_sha256` and
                        # `graph_hash` with THIS run's, so a carried table sat under a full provenance
                        # header describing a different run -- the same transplant the per-run record
                        # closed for the billed layer, surviving on the free one (DRIVEN: a layer-1
                        # re-run at 120000Z then a layer-2 run at 130000Z printed
                        # `generated: 130000Z` over a LAYER 1 table measured at 120000Z). No money and
                        # no gate ride on it -- the gate refuses this whole document by artifact class
                        # and layer 1 is free and re-derivable -- so it is STAMPED rather than moved
                        # into a record of its own. The predecessor's OWN carried stamp wins when it
                        # has one: on the third merge `_prev["generated_utc"]` is already a later run.
                        _merged[_stamp_k] = (_prev.get(_stamp_k) or _prev.get("generated_utc"))
                    else:
                        # THIS RUN MEASURED IT (or nobody did): the header stamp is the right one and a
                        # carried stamp inherited through `dict(_prev)` would now be a lie.
                        _merged.pop(_stamp_k, None)
                _seen = {b["bar"] for b in summary.get("bars") or []}
                _merged["bars"] = list(summary.get("bars") or []) + [
                    b for b in (_prev.get("bars") or []) if b["bar"] not in _seen]
                _merged["failing_bars"] = sorted({b["bar"] for b in _merged["bars"]
                                                  if b["verdict"] in ("STOP", "MISS")})
                _merged["verdict"] = ("STOP" if any(b["verdict"] == "STOP" for b in _merged["bars"])
                                      else "LAND-DARK")
                summary = _merged
        # THE POINTER LIST IS APPEND-ONLY AND IN ORDER, and it is the ONLY trace of layer 2 in this
        # file. Two calibrations on one date are therefore two entries and two files -- the attempt
        # count nothing in the tree had -- and a free layer-1 re-run adds neither.
        _runs = [r for r in (summary.get("layer2_runs") or []) if isinstance(r, dict)]
        if _pointer is not None and _pointer["file"] not in {r.get("file") for r in _runs}:
            _runs = _runs + [_pointer]
        summary["layer2_runs"] = _runs
        # AND THE LATEST VERDICT, COPIED FOR A HUMAN READER AND NAMING ITS OWN FILE. A copy that did
        # not name its file is exactly the transplant this arc closed: a verdict sitting under a
        # header that describes a different run. When this run banked no layer 2 the key is untouched,
        # so the predecessor's copy -- which names ITS file -- survives unchanged.
        if _pointer is not None and _gate:
            summary["oneshot_gate_latest"] = {"file": _pointer["file"],
                                              "generated_utc": _pointer["generated_utc"],
                                              "verdict": _gate["verdict"],
                                              "failing": list(_gate["failing"])}
        # THE PROSE HALF IS RENDERED BEFORE EITHER HALF IS WRITTEN -- the same rule the scratchpad
        # artifact follows, and for the same reason: a summary JSON on disk beside a summary markdown
        # that failed to render is two halves that disagree about what was measured.
        _summary_md = markdown(summary)
        # ── AND NOW THE RECORD, FIRST OF THE THREE FILES AND AFTER THE LAST RENDER. It stays ahead of
        #    the summary that points at it -- if the write REFUSES on a stamp collision, nothing has
        #    claimed a pointer to a file that is not there -- and it is now behind every rendering
        #    pass, so a report that cannot be produced costs the bank nothing rather than half of it.
        if record is not None:
            _rec_path = write_layer2_record(bank_dir, tag, record, payload=_rec_payload)
            print(f"record:   {_rec_path}  (the document the gate certifies -- hand THIS path on)")
        (bank_dir / f"{tag}_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
        # THE BANKED MARKDOWN IS RENDERED FROM THE SANITISED SUMMARY, never from `doc`: one producer
        # for the phrase-free rule, so a future column added to the full artifact cannot leak through
        # the prose half while the JSON half stays clean.
        (bank_dir / f"{tag}_summary.md").write_text(_summary_md, encoding="utf-8", newline="\n")
        if doc.get("latency"):
            # THE D10 BANK, ONE FILE PER DECK. The fixed name `latency.json` was a CLOBBER: the
            # summaries merge (a layer-1 re-run cannot erase a banked layer 2) but this file was
            # written unconditionally, so a `--latency` pass over the HELD-OUT deck would have
            # silently replaced the calibration bank `config_check` grades. The name now carries the
            # deck, and `config_check.SUBJECT_LATENCY_GLOB` reads every one of them and grades the
            # WORST -- so a second deck's harness run adds a measurement instead of erasing one.
            (bank_dir / f"latency_{tag}.json").write_text(
                json.dumps(dict(doc["latency"], deck=doc["deck"], graph_hash=doc["graph_hash"],
                                generated_utc=doc["generated_utc"]), indent=2, ensure_ascii=False),
                encoding="utf-8", newline="\n")
        print(f"bank:     {bank_dir}")

    print("")
    print("PRE-REGISTERED BARS")
    for b in doc["bars"]:
        print(f"  {b['verdict']:<5} {_ascii(b['bar']):<44} {_ascii(b['detail'])}"
              + (f"  rows: {_ascii(', '.join(b['rows']))}" if b.get("rows") else ""))
    if doc.get("layer2"):
        print(f"  MEASURED DOLLARS: ${doc['layer2']['usd_measured']:.4f} over "
              f"{doc['layer2']['calls']} calls (usage fields, not the anchor)")
    print(f"VERDICT: {doc['verdict']}"
          + (f" -- failing: {'; '.join(_ascii(x) for x in doc['failing_bars'])}"
             if doc["failing_bars"] else ""))
    # ── THE GATE, PRINTED LAST AND SEPARATELY, because it is the decision the run was made for and
    #    the line above is not it. See `oneshot_gate`: the exit code grades every bar together and
    #    the calibration decks carry a FATAL layer-1 carry the deck header authorises reading past,
    #    so a run whose gate is OPEN still exits 1. The gate is the fourteen pre-registered checks --
    #    the artifact's class and its file name, the layer-2 fields, plus the run's own provenance,
    #    shape and standing -- and it is read here rather than inferred there.
    if doc.get("oneshot_gate"):
        print_gate(doc["oneshot_gate"])
        # AND WHERE THE CERTIFIED DOCUMENT IS, on the line the operator acts on. The gate certifies a
        # FILE; "a run that opened" is not a path, and handing one on by description is how a second
        # attempt gets read as the first.
        if doc.get("layer2_record_file"):
            print(f"  THE CERTIFIED ARTIFACT: {bank_dir / doc['layer2_record_file']}")
        elif args.no_bank:
            print("  NO IN-TREE RECORD: this run was made with --no-bank, so the per-run record "
                  "exists only inside the scratchpad artifact above (`layer2_record`).")
    return 1 if doc["verdict"] == "STOP" else 0


if __name__ == "__main__":
    sys.exit(main())
