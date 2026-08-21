#!/usr/bin/env python
"""Assemble data/dec_p0/projection_census.{json,md} -- the PROJECTION-FAILURE CENSUS.

READ-ONLY assembler: every number in ROWS was measured in-session (S3 probes, parquet reads,
vendor-API universe calls, source reads). No estimates are recorded as facts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"C:\Users\User\Desktop\Leviathan")
OUT = REPO / "data" / "dec_p0"

GENERATED = "2026-08-20"

# ---------------------------------------------------------------------------
# ROWS -- one per family. Fields:
#   family, source, source_universe, ingested_universe, classification,
#   discard, feeds, fix_cost, evidence, desk_rank (SILENT only), axis
# classification in {FULL, DELIBERATE-SUBSET, SILENT-PROJECTION, NOT-A-SOURCE,
#                    ACQUISITION-GAP, ALREADY-BANKED}
# ---------------------------------------------------------------------------
ROWS: list[dict] = []

OUT.mkdir(parents=True, exist_ok=True)


def emit(rows: list[dict], lint: dict, counts: dict) -> None:
    payload = {
        "census": "projection_failure",
        "generated": GENERATED,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "bucket": "s3://leviathan-dev-shahem-001",
        "defect_class": (
            "A producer fetches a RICH source and silently writes a FILTERED projection, so the "
            "estate believes it 'has' the source while discarding most of it."
        ),
        "counts": counts,
        "families": rows,
        "lint": lint,
    }
    (OUT / "projection_census.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("wrote", OUT / "projection_census.json")
