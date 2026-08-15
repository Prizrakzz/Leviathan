"""CloudWatch Embedded Metric Format (EMF) emitter — Stage 5.3 R3 structured turn metrics.

A valid EMF JSON line printed to stdout is shipped by the ECS awslogs driver to CloudWatch Logs, which
auto-extracts the embedded values into custom metrics (namespace `Leviathan/Serving`) — no PutMetricData
calls and no extra IAM. The 5.2 serving dashboard reads these (turn latency p50/p95, citation strips/turn).

Every emit is fail-open: telemetry must never break or slow a turn.
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

NAMESPACE = "Leviathan/Serving"

# LANE identity, stamped on EVERY record (F0, latency RCA 2026-07-25). EMF is auto-extracted from ANY log
# group, so `Leviathan/Serving` is a blend: ~99.5% of its samples came from the AWS Batch eval harness, and
# reading that aggregate as user latency is what invalidated the RCA's rank-1 root cause. Worse, the two
# lanes are not the same system — the eval harness reranks on the LOCAL bge cross-encoder behind a global
# lock while production reranks on Bedrock Cohere, so a share measured on one lane cannot transfer to the
# other. `source` + `rerank_backend` make that mix-up impossible to repeat: no query can silently pool the
# lanes again. BOTH are CLOSED slug sets — a CloudWatch dimension is billed per distinct combination, so raw
# env text (arbitrary strings) must never reach a dimension value.
_SOURCES = ("serving", "eval", "batch", "local")
_RERANK_BACKENDS = ("bge", "bedrock", "cohere")     # D-MW-6: the native lane, or its dim collapses to `other`


def _eval_harness() -> bool:
    """True when THIS process IS the eval harness — `python -m leviathan.graphrag.eval` (the command
    `submit_eval.build_command` builds), which sets `__main__.__spec__.name`. A test or script that merely
    IMPORTS eval is not the harness, so this cannot mislabel a serving turn."""
    import sys
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return getattr(spec, "name", "") == "leviathan.graphrag.eval"


def _source() -> str:
    """`serving` (ECS task) | `eval` (the graphrag eval harness, wherever it runs) | `batch` (any other
    in-VPC Batch job, e.g. a latency probe) | `local` (laptop/pytest — never reaches CloudWatch, since
    nothing ships stdout there). The eval harness is tested FIRST: it is the eval lane on ECS-shaped or
    Batch-shaped hardware alike. GRAPHRAG_TELEMETRY_SOURCE lets a probe label itself and is slug-checked,
    so a typo or an injected value falls back to derivation instead of minting a new dimension value.

    AWS_BATCH_JOB_ID is tested BEFORE the ECS metadata var, and the order is load-bearing: this account's
    Batch queue runs on FARGATE (compute env leviathan-dev-fargate-ondemand), and Fargate-backed Batch
    containers DO carry ECS_CONTAINER_METADATA_URI_V4 — the ECS-first order labelled every non-eval Batch
    job (a latency probe, an in-VPC parity run) `serving`, poisoning the one series F0 exists to keep
    clean. A Batch job is never the serving task; a serving task never has AWS_BATCH_JOB_ID."""
    override = os.environ.get("GRAPHRAG_TELEMETRY_SOURCE", "").strip().lower()
    if override in _SOURCES:
        return override
    if _eval_harness():
        return "eval"
    if os.environ.get("AWS_BATCH_JOB_ID"):
        return "batch"
    if os.environ.get("ECS_CONTAINER_METADATA_URI_V4") or os.environ.get("ECS_CONTAINER_METADATA_URI"):
        return "serving"                      # injected by the ECS agent on the real serving task
    return "local"


def _rerank_backend() -> str:
    """`bge` | `bedrock` | `cohere`, resolved through rankers so there is exactly ONE resolution path (env >
    params > code default `bge`) — a second copy of that precedence here is how the two lanes drifted
    unnoticed in the first place. Anything else is reported as `other` rather than passed through."""
    try:
        from leviathan.graphrag import rankers as rk
        b = rk._rerank_backend()
    except Exception:  # noqa: BLE001 — telemetry must never break a turn
        return "unknown"
    return b if b in _RERANK_BACKENDS else "other"


# ── D-HP-17 / D-HP-20: THE SUCCESSOR METRIC FAMILY ──────────────────────────────────────────────────────
# The strip classes, named ONCE. Every consumer (the eval artifact columns, the EMF counters, the gate
# readouts) derives from THIS module so the arithmetic cannot be retyped and drift -- the COMPAT-9 class.
# The spellings are verify.py's `by_rule` keys and they are a CONTRACT with the verifier seam: a rule
# renamed there and not here reads as 0 forever, which is the one failure mode that would let this family
# congratulate the wave (D5). `test_dmw_eval_instruments` pins the tuples.
#
# READING RULE (D-HP-17, folded review G21): `by_rule` accrues by `get(rule, 0) + 1`, so a CLEAN ROW STORES
# `{}`. Every read below is `.get(class, 0)`; an absent key means the class did not fire.
KILLED_CLASSES: tuple[str, ...] = ("fabricated_citation", "ledger_cascade", "number_unbacked",
                                   "undeclared_unsupported")
RESIDUAL_CLASSES: tuple[str, ...] = ("no_lexical_overlap", "quote_mismatch", "foreign_regime_name",
                                     "index_out_of_range")
# BLINDED, NEVER KILLED (D-HP-17 item 2b): under handle-prose the verifier runs at answer.py:2191 and the
# splice at :2229-2249, so it sees prose with NO DIGITS and these two cannot fire -- they go to zero BY
# ORDERING, not by improvement. `number_unbacked` is deliberately in BOTH tuples: it is killed by a NEW
# FENCE (the digit-lint) and blinded by the ordering, and reporting it in only one place would hide one of
# the two mechanisms. That overlap is why `unconstructible_count` is ALWAYS read beside `bare_digit_strips`
# and RAW `strips` -- a run where the first is 0 while the other two are flat has RENAMED a class.
BLINDED_CLASSES: tuple[str, ...] = ("number_mismatch", "number_unbacked")
# The wave's #1 risk (D-HP-17 item 2c). `number_mismatch` is deliberately NOT here (REVIEW RECORD,
# CONFLICT 4). The third term rides `wrong_slot_audit.scope_mismatch`, added below.
#
# ══ H1 FIX Z1 -- WHERE THESE TWO ARE WRITTEN, AND THE DEDUP RULE FOR THE THIRD TERM ═══════════════════
# THEY REACH `by_rule` NOW, AND THAT IS THE FIX. Both classes are decided in the RENDER pass
# (`answer._resolve_number_handles`) and were written only into `trace['number_handles']`, so this family
# -- reading `by_rule`, as the contract above says it must -- scored `direction_sign_mismatch` as 0
# FOREVER while every one of its convictions DELETED A SENTENCE from the page. That is the D5 failure the
# block comment above names: the one shape in which this family congratulates the wave.
# `answer._fold_render_classes` folds them (and `grouped_in_slot`) into the verifier's ONE strip ledger,
# with `stripped` incremented alongside so the ledger's own sum invariant holds. Treatment-lane only, so a
# control row's `by_rule` is byte-identical. The class scan (G1 clause (4)) reads the same location and is
# no longer blind to three of the four D-HP-native classes.
#
# THE DEDUP RULE, STATED HERE BECAUSE THIS IS WHERE THE ARITHMETIC LIVES. D-HP-17 item 2c names THREE
# terms, and the third -- `wrong_slot_audit.scope_mismatch` -- is a PROJECTION of the first, not an
# independent measurement (`answer._wrong_slot_audit` builds it from the same counter; two producers for
# one risk is how a census reads 0 while the page lost a sentence). Summing all three verbatim counts the
# SCOPE class TWICE. So all three are READ and the third contributes only its EXCESS over its own mirror:
#     mis_bound = by_rule[scope] + by_rule[direction] + max(0, wsa[scope] - by_rule[scope])
# With the mirror live the excess is 0 and the metric is `scope + direction`, which is what R11's ceiling
# of 15 and the per-row tripwire are written against. On a PRE-MIRROR artifact (`by_rule` carries no
# scope term) the excess is the whole projection, so an older row still reports its scope events instead
# of silently dropping them. One expression, correct on both populations, and no term is ignored.
#
# ══ D-HP-25 (plan 10.30.6) -- THE TWO BINDING-VERIFIER CLASSES JOIN, AND THE DEDUP RULE STILL HOLDS ════
# `geo_mismatch` (V1, the [N] geo axis) and `evidence_geo_contradiction` (V2, the [E] containment pass)
# are BOTH mis-bindings: a receipt that names the wrong GEOGRAPHY is a wrong receipt exactly as one that
# names the wrong PERIOD is. Excluding them would let this wave count the finds and not the finding --
# GAMING OUR OWN GATE -- and plan 10.30.6 pre-refuses that in advance of any number existing to argue
# about. CONSEQUENCE, PRE-REGISTERED AND NOT NEGOTIABLE: they consume R11's FROZEN CEILING OF 15 POOLED
# PER TREATMENT ARM, and the 15 itself may not be moved. If the new classes push an arm past 15 that is a
# FAIL to be RCA'd, never a ceiling to be raised.
# THE PROJECTION DEDUP IS UNAFFECTED, AND THE REASON IS STRUCTURAL RATHER THAN ARITHMETIC.
# `MIS_BOUND_PROJECTION` mirrors `MIS_BOUND_CLASSES[0]` (`slot_scope_mismatch`) alone, and
# `answer._resolve_number_handles` seats the geo check INSIDE the direction check's `else`, so ONE HANDLE
# CAN BE CONVICTED BY AT MOST ONE OF THE THREE [N] CLASSES. The expression below therefore stays exact:
# no handle contributes a scope term AND a geo term, so nothing is double-counted and the `max(0, ...)`
# excess term keeps reading pre-mirror artifacts correctly.
MIS_BOUND_CLASSES: tuple[str, ...] = ("slot_scope_mismatch", "direction_sign_mismatch",
                                      "geo_mismatch", "evidence_geo_contradiction")
MIS_BOUND_PROJECTION: str = "scope_mismatch"        # `wrong_slot_audit`'s mirror of MIS_BOUND_CLASSES[0]
BARE_DIGIT_CLASS: str = "bare_digit"
# ══ H1 FIX W2 -- `slot_orphan` IS IN `by_rule` AND IN NO TUPLE ABOVE, DELIBERATELY ════════════════════
# `answer._fold_ledger_class` folds the Z4/W1 remedy's whole-sentence deletions into the ONE ledger as
# `by_rule['slot_orphan']` (+ `stripped`), so the CLASS SCAN and the per-answer projection can see a
# removal that previously existed only on the live turn's trace (finding NF-2). It is named in G1 clause
# (4)'s declared set (plan 10.11) so the scan reads it rather than failing on it.
# IT JOINS NO SUCCESSOR COUNTER, and each exclusion is a decision, not an oversight:
#   * NOT `KILLED_CLASSES`   -- it kills nothing the verifier had not already convicted; the conviction is
#                               charged under its OWN class and counting it twice would inflate the
#                               wave's central "unconstructible" claim with its own remedy.
#   * NOT `RESIDUAL_CLASSES` -- those are the four that survive BY CONSTRUCTION at the verifier; this is a
#                               RENDER-side consequence of one of them, and pooling the two would double
#                               the residual band D-HP-18 derived from stored artifacts.
#   * NOT `MIS_BOUND_CLASSES`-- nothing was mis-bound; the handle was STRIPPED, not wrongly resolved.
# CONSEQUENCE FOR THE READER OF `strips`: raw `stripped` on the treatment arm now carries FOUR D-HP-native
# classes with no control-arm counterpart (three from Z1's fold, plus this one), which is why the arm
# comparison is the class scan and never a raw stripped delta -- stated as a G1 pre-registration sentence
# at plan D-HP-21 clause (3) rather than left as a property of this file.
#
# ══ H1b (D-HP-15) -- `episode_span_unbacked` IS IN `by_rule` AND IN NO TUPLE ABOVE, DELIBERATELY ══════
# `answer._validate_episode_spans` deletes a model episode bullet whose window this turn's prompt never
# carried, and `answer._fold_ledger_class` folds those deletions into the ONE ledger as
# `by_rule['episode_span_unbacked']` (+ `stripped`), so the class scan and the per-answer projection can
# read a removal that would otherwise exist only on the live turn's trace. It is DECLARED in G1 clause
# (4)'s frozen set (plan 10.13) in the same change, so the scan reads it rather than failing on it.
# THE EXCLUSIONS, each a decision and not an oversight -- and note they are NOT the `slot_orphan`
# argument, because this class IS a conviction of its own:
#   * NOT `KILLED_CLASSES`   -- those four are the AC1 classes, and plan 10.10(c) forbids ANY gate clause
#                               attributing an AC1 result to D-HP-15 (the section carries 0.9% of typed
#                               numerals). Pooling an episode-window conviction into `unconstructible_count`
#                               would do exactly that, by arithmetic, in the wave's headline metric.
#   * NOT `RESIDUAL_CLASSES` -- those are the four that survive BY CONSTRUCTION at the verifier. This one
#                               is a RENDER-side conviction with its own remedy, and pooling it would
#                               inflate the residual band D-HP-18 derived from stored artifacts.
#   * NOT `MIS_BOUND_CLASSES`-- nothing was mis-bound; no handle was resolved to the wrong row. The
#                               fabricated object is the WINDOW, which addresses no menu row at all.
# ITS BUDGET LIVES IN G1 CLAUSE (e-ep), NOT HERE: zero on every control row (the mutation is
# treatment-gated, so a control charge is an instrument defect), REPORTED against a pre-registered
# ceiling on the treatment arm. The per-turn denominator is `trace['episode_spans_validated']`.
#
# ══ H2 (D-HP-17/18, THE METRIC TRANSITION) -- THE CLASS SCAN, WHICH IS WHAT CARRIES THE COVENANT ══════
# Section 2 names the CLASS SCAN -- not any rate -- as the regression detector, and D-HP-18's derivation
# (data/dhp_h2_residual_band.json) records the residual band UNUSABLE, so after this boundary the scan is
# the ONLY pre-D-HP instrument that survives. It therefore stops being a thing a gate reader retypes off a
# report and becomes a produced surface, here, beside the tuples it reads (the COMPAT-9 one-producer class).
#
# `G1_DECLARED_CLASSES` IS G1 CLAUSE (4)'s FROZEN DECLARED SET, ENUMERATED IN THE CLAUSE'S OWN ORDER: the
# 19a five, PLUS the three that survive by construction, PLUS `undeclared_unsupported`, PLUS the D-HP-native
# charging classes, PLUS `slot_orphan` (H1 FIX W2) and `episode_span_unbacked` (H1b / D-HP-15). A class
# OUTSIDE this set that reproduces in BOTH runs is what clause (4) fails on; the set is frozen at first arm,
# not here, and every member's reason is written at the clause. THE SPELLINGS ARE THE SEAM CONTRACT (the
# rule stated at KILLED_CLASSES): these fifteen are every class `verify.py` can charge (`_check_number_handle`
# -> index_out_of_range / number_mismatch / number_unbacked; the ledger branches -> fabricated_citation /
# ledger_cascade / undeclared_unsupported; the prose checks -> no_lexical_overlap / quote_mismatch /
# foreign_regime_name; the digit-lint -> bare_digit) plus the five `answer._fold_ledger_class` folds in.
#
# ══ D-HP G1 REMEDIATION D2(b) (2026-08-14) -- `evidence_handle_in_slot` IS THE SIXTEENTH MEMBER ════════
# `answer._resolve_evidence_handles` now severs the clause (or drops the sentence) carrying a FULLY
# RESOLVED [E] handle that stands behind a value cue -- G1 clause (2b)'s escape, measured at 7 events over
# 4 treatment rows on the r2 run set with no remedy anywhere in the stack. `answer._fold_ledger_class`
# folds those removals into the ONE ledger, so it is DECLARED here in the same change or clause (4) would
# be pre-registered to fail on the wave's own remedy (the `slot_orphan` / `episode_span_unbacked` rule).
# THE SET IS FROZEN AT FIRST ARM, NOT HERE: this member joins at the RE-FREEZE that follows the
# remediation window, and the clause's own text must name it there.
# IT JOINS NO SUCCESSOR TUPLE, each exclusion a decision:
#   * NOT `KILLED_CLASSES`   -- it is not one of the four AC1 classes and pooling a render-side conviction
#                               into `unconstructible_count` would inflate the wave's headline claim with
#                               its own remedy (the `slot_orphan` argument, restated).
#   * NOT `RESIDUAL_CLASSES` -- those four survive BY CONSTRUCTION at the verifier; this is a RENDER-side
#                               conviction with its own remedy and would double D-HP-18's residual band.
#   * NOT `MIS_BOUND_CLASSES`-- NOTHING WAS MIS-BOUND, and that is the sharpest reason: the handle
#                               resolved and named the right item. What was wrong is the SLOT it stood in,
#                               which is `grouped_in_slot`'s question, not R11's.
G1_DECLARED_CLASSES: tuple[str, ...] = ("fabricated_citation", "ledger_cascade", "no_lexical_overlap",
                                        "number_mismatch", "number_unbacked",
                                        "quote_mismatch", "index_out_of_range", "foreign_regime_name",
                                        "undeclared_unsupported",
                                        "bare_digit", "direction_sign_mismatch", "slot_scope_mismatch",
                                        "grouped_in_slot", "slot_orphan", "episode_span_unbacked",
                                        "evidence_handle_in_slot",
                                        # ── D-HP-25 (plan 10.30.6): THE SEVENTEENTH AND EIGHTEENTH.
                                        # MANDATORY, and the reason is that clause (4) is a CLASS SCAN
                                        # over `by_rule`: an UNDECLARED class FAILS THE CLAUSE ON ITS
                                        # OWN REMEDY. A verifier that breaks the gate by WORKING is a
                                        # defect, not a result. `geo_mismatch` folds via
                                        # `answer._fold_render_classes` (it is in
                                        # `_RENDER_LEDGER_CLASSES`); `evidence_geo_contradiction` folds
                                        # via `answer._fold_ledger_class` at both serving bodies. Both
                                        # are ALSO in `MIS_BOUND_CLASSES` above -- unlike
                                        # `evidence_handle_in_slot`, which convicts the SLOT and not the
                                        # binding -- and NEITHER is in `KILLED_CLASSES`.
                                        "geo_mismatch", "evidence_geo_contradiction")
# THE ARM-EXCLUSIVE CLASSES -- the ones that CANNOT be charged on a control row, so a RAW `stripped` delta
# across the arms is not a like-for-like quantity. G1 clause (3) states the caution and X5 corrected its
# count from four to FIVE; **H2 CORRECTS IT AGAIN, TO SIX**, and the sixth is H1b's own: `episode_span_
# unbacked` folds into `by_rule` + `stripped` like the other five and its pass MUTATES ONLY under
# `handle_prose` ((e-ep)(i) makes a control charge an INSTRUMENT DEFECT that voids the run set), so it too
# has no control-arm counterpart. X5 was written one fold before H1b landed the class; the count is
# arithmetic over this tuple now instead of a sentence that has to be re-counted by hand.
# D-HP G1 REMEDIATION D2(b): **SEVEN**, and the seventh is `evidence_handle_in_slot` -- the remedy pass
# mutates only under `handle_prose` and the census key is not even minted on a control turn, so like the
# six above it has no control-arm counterpart and a raw `stripped` delta across the arms is not like for
# like. The count is arithmetic over this tuple, never a sentence to be re-counted by hand (X5's lesson).
# D-HP-25 (plan 10.30.6): **NINE**, and the eighth and ninth are the binding verifier's own. Both passes
# mutate ONLY under `handle_prose` (V1's census keys are not even minted on a control turn, V2's pass is
# not called), so like the seven above they have no control-arm counterpart and a raw `stripped` delta
# across the arms is not like for like. The count is arithmetic over this tuple, never a sentence to be
# re-counted by hand (X5's lesson, restated a third time).
ARM_EXCLUSIVE_CLASSES: tuple[str, ...] = ("bare_digit", "slot_scope_mismatch", "direction_sign_mismatch",
                                          "grouped_in_slot", "slot_orphan", "episode_span_unbacked",
                                          "evidence_handle_in_slot",
                                          "geo_mismatch", "evidence_geo_contradiction")

# ══ H2 FOLD 1 (K1) -- G1 CLAUSE (8)'s DENOMINATOR, AS ARITHMETIC RATHER THAN AS A SENTENCE ════════
# Clause (8) reads `number_handles.substituted + prose_handles.substituted` per answer against **0.6 x the
# CONTROL arm's mean TYPED-NUMERAL count per answer ON THE SAME DECK**. H2 produced the NUMERATOR
# (`quality_counters.substitution_load` -> `dhp_successor.substitution_load_mean`) and left the DENOMINATOR
# to a gate reader with no shipped producer to read it from -- the SAME C2/U3 defect H2 had just repaired
# for clause (2b), left standing on a clause that FAILS G1 "regardless of the strip classes".
#
# THE DENOMINATOR ALREADY HAS A PRODUCER, AND NAMING IT IS THE FIX -- NO SECOND EXTRACTOR IS MINTED HERE.
# `bare_digit_escapes` (see `quality_counters`) reads `trace["bare_digit_count"]` =
# `answer._count_bare_digits(structured)`, which counts CLAIM MAGNITUDES on the PRE-VERIFY `tldr` +
# `mechanism` -- the exact text `answer.raw_draft_snapshot` captures as `raw_draft.preverify_*` three lines
# later, before `verify_citations` mutates it -- using `verify._mask_handles` + `_claim_numbers_with_
# decimals`, the extractor clause (8) NAMES BY NAME and the one `dhp_census.json` itself ran
# (`method.extractor`), which is what makes the census anchor of 19.8 numerals per answer commensurable
# with it at all. It is ALWAYS ON, on BOTH ARMS, and it gates nothing (D-HP-4(c)), so the control arm's
# mean is a COLUMN ON THE CONTROL ARTIFACT rather than a number a gate owner re-derives from a corpus.
# (A THIRD EXTRACTOR WAS AVAILABLE AND IS REFUSED: `orchestrator._stated_values` and
# `register._level_tokens` carry different exemption sets, each fixed after its own live false-caution
# incident -- D-HP-3's whole point.)
#
# THE FACTOR AND THE MULTIPLY LIVE HERE, beside the tuples, so the eval projection, a gate reader and any
# later re-read of the stored corpus cannot disagree about the bar. WHAT DOES NOT LIVE HERE IS THE
# COMPARISON: clause (8) is a TWO-ARTIFACT read (the treatment run's `substitution_load_mean` against the
# CONTROL run's `substitution_floor` on the SAME DECK), so this returns a FLOOR and never a verdict --
# the same reason `blocking_classes` takes two scans instead of pooling them.
SUBSTITUTION_FLOOR_FACTOR: float = 0.6


def substitution_floor(typed_numeral_mean) -> float:
    """G1 CLAUSE (8)'s BAR, from ONE arm's mean typed-numeral count per answer. Never raises.

    READ IT OFF THE **CONTROL** ARTIFACT: it is the floor the TREATMENT arm's `substitution_load_mean` on
    the same deck must clear, below which the arm is NUMBER-AVOIDING and the gate fails regardless of the
    strip classes. It is computed on BOTH arms for the reason clause (2b)'s instrument is recorded on both:
    a bar with no measured counterpart on the other arm is not a measurement. On the treatment arm it is
    expected to collapse toward zero -- that collapse IS the wave's claim, and it is a reading, not a bar."""
    try:
        return round(SUBSTITUTION_FLOOR_FACTOR * float(typed_numeral_mean or 0.0), 4)
    except Exception:  # noqa: BLE001 -- an instrument never breaks a turn
        return 0.0


def class_scan(by_rules) -> dict:
    """G1 CLAUSE (4)'s CLASS SCAN over one RUN, from the `by_rule` dicts of the rows the contract binds.

    ONE RUN, NEVER TWO: the intersection law ("a new class blocks only if it reproduces in BOTH runs") is
    `blocking_classes` below, which takes two of these. Pooling two runs into one scan would silently
    satisfy the law by addition, which is the shape it exists to refuse.

    RETURNS, and each key is a sentence a gate owner reads rather than derives:
      pooled            {class: events} over the rows passed in -- the run's histogram
      classes_present   sorted classes with a non-zero count (the set the intersection law operates on)
      undeclared        classes present and NOT in `G1_DECLARED_CLASSES` -- clause (4)'s failure candidates
      arm_exclusive     the subset of `pooled` with no control-arm counterpart, itemised
      arm_exclusive_total   their sum -- the exact amount by which a RAW `stripped` delta is not
                        like-for-like (clause (3)); reported so the reader subtracts nothing by hand
      rows_charged      {class: rows} -- concentration, since 30.8% of the pre-D-HP corpus's strips sat in
                        the worst 10% of answers, and a pooled count cannot say that
      rows              how many rows the scan read (the NAMED denominator; the caller excludes the
                        non-reasoning lane by id, per G1 clause (5))
      total_events      sum(pooled) -- equals the rows' `stripped` sum when the ledger invariant holds

    `by_rule` accrues by `get(rule, 0) + 1`, so a CLEAN ROW STORES `{}` and every read here is a `.get`.
    Never raises: an instrument is never worth a billed run's artifact."""
    pooled: dict[str, int] = {}
    rows_charged: dict[str, int] = {}
    n = 0
    try:
        for by in (by_rules or ()):
            n += 1
            if not isinstance(by, dict):
                continue
            for cls, c in by.items():
                c = _i(c)
                if c <= 0:
                    continue
                key = str(cls)
                pooled[key] = pooled.get(key, 0) + c
                rows_charged[key] = rows_charged.get(key, 0) + 1
    except Exception:  # noqa: BLE001 -- an instrument must never break a run
        pass
    present = sorted(pooled)
    return {"pooled": {k: pooled[k] for k in present},
            "classes_present": present,
            "undeclared": [k for k in present if k not in G1_DECLARED_CLASSES],
            "arm_exclusive": {k: pooled[k] for k in present if k in ARM_EXCLUSIVE_CLASSES},
            "arm_exclusive_total": sum(pooled[k] for k in present if k in ARM_EXCLUSIVE_CLASSES),
            "rows_charged": {k: rows_charged[k] for k in present},
            "rows": n,
            "total_events": sum(pooled.values())}


def blocking_classes(scan_a: dict, scan_b: dict) -> list[str]:
    """THE INTERSECTION LAW AS ARITHMETIC (section 2): an undeclared class blocks G1 clause (4) only if it
    reproduces in BOTH runs of the arm. Returns the sorted intersection of the two runs' `undeclared` lists
    -- empty is the pass shape. A class in exactly one run is RECORDED by the caller, never a block."""
    try:
        return sorted(set(scan_a.get("undeclared") or ()) & set(scan_b.get("undeclared") or ()))
    except Exception:  # noqa: BLE001
        return []


def _i(v) -> int:
    try:
        return int(v or 0)
    except Exception:  # noqa: BLE001 -- a counter never breaks a turn
        return 0


def quality_counters(trace: Optional[dict]) -> Optional[dict]:
    """THE ONE PRODUCER of the D-HP-17 successor family, from one turn's `trace` dict.

    Returns None when the CITATION verifier did not run on this turn -- the numbers_only / live lane has no
    structured tldr/mechanism and is verified by `orchestrator._verify_numbers_answer` instead. That lane is
    the DECLARED NON-REASONING lane (D-HP-17's denominator accounting, G1 clause (5)) and it is excluded
    HERE, once, rather than by each consumer: a fake 0 from a lane the contract does not bind would dilute
    every counter it is pooled into.

    The keys are the ARTIFACT names (snake_case). `emit_quality` maps them to the five CloudWatch counters.
      unconstructible_count  the wave's own claim -- pre-registered EXACTLY 0 on every treatment row
      residual_strips        the four classes that survive by construction (RECORDED, scored on neither arm)
      blinded_class_count    the two classes that go to zero by ORDERING (reported as BLINDED, never killed)
      mis_bound_count        the #1 risk as a number; ceiling 15 pooled per treatment arm (R11)
      bare_digit_strips      the digit-lint's CONVICTIONS (a by_rule class, `strips` counts it too)
      bare_digit_escapes     the digit-lint's ESCAPES (`trace.bare_digit_count`, always-on, gates nothing)
      handles_unresolvable   the model addressed a receipt that does not exist -- the wave's residual.
                             NARROWED 2026-08-14 (G1 REMEDIATION-2 R2-a, plan 10.19): on the TREATMENT
                             lane an EMPTY-ROW address (the receipt exists and carries no value) now
                             lands in `number_handles.empty_row_addressed` instead, so this column is
                             the invented-receipt population only. The CONTROL lane is unchanged (the
                             OFF-arm-clean rule), so a cross-arm read of this one column is NOT like
                             for like after that date -- `dhp_refusals` carries both halves.
      substitution_load      the NUMBER-AVOIDANCE instrument (B7 / G1 clause (8)), denominated per answer
                             against the census's ALL-ANSWERS mean of 19.8 typed numerals
    """
    try:
        tr = trace or {}
        v = (tr.get("citation_verifier") or {})
        if not v.get("enabled"):
            return None
        by = v.get("by_rule") or {}
        nh = tr.get("number_handles") or {}
        ph = tr.get("prose_handles") or {}
        wsa = tr.get("wrong_slot_audit") or {}
        return {
            "unconstructible_count": sum(_i(by.get(k)) for k in KILLED_CLASSES),
            "residual_strips": sum(_i(by.get(k)) for k in RESIDUAL_CLASSES),
            "blinded_class_count": sum(_i(by.get(k)) for k in BLINDED_CLASSES),
            # FIX Z1: all three terms, with the projection deduplicated against its own mirror. See the
            # rule stated at MIS_BOUND_CLASSES -- it is the arithmetic, not a comment about it.
            "mis_bound_count": (sum(_i(by.get(k)) for k in MIS_BOUND_CLASSES)
                                + max(0, _i(wsa.get(MIS_BOUND_PROJECTION))
                                      - _i(by.get(MIS_BOUND_CLASSES[0])))),
            "bare_digit_strips": _i(by.get(BARE_DIGIT_CLASS)),
            "bare_digit_escapes": _i(tr.get("bare_digit_count")),
            "handles_unresolvable": _i(nh.get("unresolvable")) + _i(ph.get("unresolvable")),
            "substitution_load": _i(nh.get("substituted")) + _i(ph.get("substituted")),
        }
    except Exception:  # noqa: BLE001 -- an instrument must never break a turn
        return None


# artifact name -> CloudWatch counter name. FIVE counters exactly, which is the number R14 priced.
_QUALITY_EMF_NAMES: dict[str, str] = {"unconstructible_count": "Unconstructible",
                                      "residual_strips": "ResidualStrips",
                                      "bare_digit_escapes": "BareDigits",
                                      "handles_unresolvable": "HandlesUnresolvable",
                                      "mis_bound_count": "MisBound"}


def emit_quality(trace: Optional[dict]) -> None:
    """D-HP-20 change (2): the successor counters, emitted BESIDE `StripCount` from the same seam.

    FLEET-DIMENSIONED ONLY (`dimensions=None`), per R14's ratified answer to the recurring-cost question: a
    CloudWatch dimension bills per DISTINCT COMBINATION, so riding the turn emitter's
    (intent x model x mode) set would bill five counters x that cardinality every month, forever, for a
    per-intent cut that Logs Insights can already produce from the lane fields. `emit()` still attaches its
    own LANE set (source / rerank_backend) and the fleet aggregate, so `source=serving` remains filterable
    -- which is the same dimension D-HP-20 change (1) needs the WIDGET to start using.

    WHY THIS EXISTS AS ITS OWN CALL AND NOT AS FIVE KEYS IN THE TURN EMITTER: those five keys would inherit
    the turn emitter's dimension set, which is exactly the bill R14 refused. One call, one dimension
    decision, one place to change it.

    Silent no-op on a turn whose citation verifier never ran (`quality_counters` returns None), so the
    numbers lane cannot dilute a panel that reads as a quality signal."""
    q = quality_counters(trace)
    if not q:
        return
    emit({emf_name: q[k] for k, emf_name in _QUALITY_EMF_NAMES.items() if k in q},
         dimensions=None, units={n: "Count" for n in _QUALITY_EMF_NAMES.values()})


def emit(metrics: dict[str, float], *, dimensions: Optional[dict[str, str]] = None,
         units: Optional[dict[str, str]] = None) -> None:
    """Print one EMF record. `metrics` = {name: value}. `dimensions` become CloudWatch dimensions (and, per
    the EMF spec, are duplicated as top-level fields). Each metric is emitted BOTH with the dimension set and
    without dimensions (`[]`) so the dashboard can graph a fleet-wide aggregate as well as per-(intent,model).

    The lane fields (`source`, `rerank_backend`) are added to every record as top-level fields — so Logs
    Insights can ALWAYS filter on them — plus ONE dimension set of their own. Their own set, not merged into
    the caller's: merging would re-dimension every metric and fork the per-(intent, model) series the 5.2
    dashboard reads, while a separate set costs one extra billed combination per environment (a given log
    group only ever emits one source and one backend)."""
    try:
        dims = {k: str(v) for k, v in (dimensions or {}).items() if v is not None and str(v) != ""}
        try:
            lane = {"source": _source(), "rerank_backend": _rerank_backend()}
        except Exception:  # noqa: BLE001 — a lane-derivation failure must not cost the whole record
            lane = {}
        units = units or {}
        vals = {n: v for n, v in metrics.items() if v is not None}
        if not vals:
            return
        dim_sets: list[list[str]] = []
        for keys in (list(dims), list(lane)):
            if keys and keys not in dim_sets:        # skip an empty/duplicate set (invalid EMF, double bill)
                dim_sets.append(keys)
        dim_sets.append([])                          # the fleet-wide aggregate always rides last
        doc = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": NAMESPACE,
                    "Dimensions": dim_sets,
                    "Metrics": [{"Name": n, "Unit": units.get(n, "None")} for n in vals],
                }],
            },
            **dims,
            **lane,
            **vals,
        }
        print(json.dumps(doc, default=str), flush=True)
    except Exception:  # noqa: BLE001 — telemetry must never break a turn
        pass
