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
_RERANK_BACKENDS = ("bge", "bedrock")


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
    """`bge` | `bedrock`, resolved through rankers so there is exactly ONE resolution path (env >
    params > code default `bge`) — a second copy of that precedence here is how the two lanes drifted
    unnoticed in the first place. Anything else is reported as `other` rather than passed through."""
    try:
        from leviathan.graphrag import rankers as rk
        b = rk._rerank_backend()
    except Exception:  # noqa: BLE001 — telemetry must never break a turn
        return "unknown"
    return b if b in _RERANK_BACKENDS else "other"


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
