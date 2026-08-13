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
MIS_BOUND_CLASSES: tuple[str, ...] = ("slot_scope_mismatch", "direction_sign_mismatch")
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
      handles_unresolvable   the model addressed a receipt that does not exist -- the wave's residual
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
