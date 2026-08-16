"""SILVER-F082 freshness poller -- LOCAL CLI SHIM.

The poller itself moved to ``jobs/observability/freshness_poller_task.py`` on 2026-08-16
(D-SG G3-1). The reason is in that module's docstring: the worker image copies ``jobs/`` and NOT
``scripts/``, so the scheduled run could only ever be a hand-transcribed ``python -c`` copy of
this file living inside terraform -- and that copy drifted from this file twice in one quarter,
silently, costing first the timeline artifact's entire metric (R7a) and then
``FreshnessLagRatio`` in its entirety (D-SG). A file that cannot be run by the scheduler must not
also be the file the scheduler's copy is transcribed FROM.

This shim is retained so the documented local command keeps working and so no runbook, ticket or
comment that names this path goes stale. It holds no logic: drift is now impossible by
construction.

    python scripts/silver/freshness_poller.py --dry-run
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobs.observability.freshness_poller_task import main  # noqa: E402

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
