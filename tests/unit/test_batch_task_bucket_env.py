# -*- coding: utf-8 -*-
"""THE BATCH TASKS READ ONE BUCKET NAME (2026-09-25).

Every Batch job definition sets LEVIATHAN_BUCKET (infra/terraform/modules/batch/main.tf) and no job definition sets
S3_BUCKET. Two gold producers read S3_BUCKET and failed every scheduled fire from 2026-09-24 before their first S3
read. This pin holds the convention over every task under jobs/batch so the next outlier fails here, in the suite,
not in the scheduler's log two days after it was written."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BATCH = ROOT / "jobs" / "batch"
_ENV_READ = re.compile(r"""get_required_env\(\s*["']([A-Z0-9_]+)["']\s*\)|os\.environ(?:\.get)?\s*[\[(]\s*["']([A-Z0-9_]+)["']|os\.getenv\(\s*["']([A-Z0-9_]+)["']""")


def _bucket_names_read(path: Path) -> set[str]:
    names = set()
    for m in _ENV_READ.finditer(path.read_text(encoding="utf-8")):
        name = next(g for g in m.groups() if g)
        if name.endswith("BUCKET"):
            names.add(name)
    return names


def test_no_batch_task_reads_a_bucket_name_no_jobdef_sets():
    offenders = {}
    for p in sorted(BATCH.glob("*.py")):
        bad = {n for n in _bucket_names_read(p) if n != "LEVIATHAN_BUCKET"}
        if bad:
            offenders[p.name] = sorted(bad)
    assert offenders == {}, offenders


def test_the_two_gold_producers_read_the_estates_bucket_name():
    for name in ("gold_futures_spreads_task.py", "gold_board_crush_task.py"):
        assert _bucket_names_read(BATCH / name) == {"LEVIATHAN_BUCKET"}, name
