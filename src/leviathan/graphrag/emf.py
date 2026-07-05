"""CloudWatch Embedded Metric Format (EMF) emitter — Stage 5.3 R3 structured turn metrics.

A valid EMF JSON line printed to stdout is shipped by the ECS awslogs driver to CloudWatch Logs, which
auto-extracts the embedded values into custom metrics (namespace `Leviathan/Serving`) — no PutMetricData
calls and no extra IAM. The 5.2 serving dashboard reads these (turn latency p50/p95, citation strips/turn).

Every emit is fail-open: telemetry must never break or slow a turn.
"""
from __future__ import annotations

import json
import time
from typing import Optional

NAMESPACE = "Leviathan/Serving"


def emit(metrics: dict[str, float], *, dimensions: Optional[dict[str, str]] = None,
         units: Optional[dict[str, str]] = None) -> None:
    """Print one EMF record. `metrics` = {name: value}. `dimensions` become CloudWatch dimensions (and, per
    the EMF spec, are duplicated as top-level fields). Each metric is emitted BOTH with the dimension set and
    without dimensions (`[]`) so the dashboard can graph a fleet-wide aggregate as well as per-(intent,model)."""
    try:
        dims = {k: str(v) for k, v in (dimensions or {}).items() if v is not None and str(v) != ""}
        units = units or {}
        vals = {n: v for n, v in metrics.items() if v is not None}
        if not vals:
            return
        dim_sets = [list(dims.keys()), []] if dims else [[]]
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
            **vals,
        }
        print(json.dumps(doc, default=str), flush=True)
    except Exception:  # noqa: BLE001 — telemetry must never break a turn
        pass
