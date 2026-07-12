#!/usr/bin/env python
"""SILVER-F062: standard job/publisher protocol adoption checklist + non-adopter lint.

Every producer family must migrate from bespoke args/writes to the common contract: an EXPLICIT
INV-2 pyarrow writer schema pinned from the F010 registry (``leviathan.silver.flat_producer``) AND
a write routed through the SILVER-F015 shadow-first publisher, exposed behind the standard
``--publish-mode`` CLI. This lint reads the registry + each producer's batch-task source and reports,
per table, the four adoption criteria:

    registry_producer  -- producer.status == producer with a transform + batch_task recorded
    writer_schema_pinned -- the contract's INV-2 pin flag
    publisher_adopted  -- the batch_task source routes through the common publisher
                          (flat_producer / ShadowPublisher / authorize_publish)
    standard_cli       -- the batch_task exposes --publish-mode

``adopted`` = all four true. An INTEGRITY violation (writer_schema_pinned True but the writer does
NOT route through the publisher -- a dishonest pin) is a HARD failure in ``--strict``.

READ-ONLY + AWS-FREE. Emits reports/silver_readiness/R2R3_producers/F062_adoption.{json,md}.

Usage:
    python scripts/silver/f062_adoption_lint.py            # write the report
    python scripts/silver/f062_adoption_lint.py --strict   # exit 3 if any INTEGRITY violation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver.registry import load_registry  # noqa: E402

OUT_DIR = _REPO / "reports" / "silver_readiness" / "R2R3_producers"

# Source markers that prove a batch task routes its write through the common publisher.
_PUBLISHER_MARKERS = ("build_flat_publish", "ShadowPublisher", "authorize_publish",
                      "authorize_for_contract", "publish_guard")
_CLI_MARKER = "--publish-mode"
_STANDARD_ARGS_MARKER = "add_standard_producer_args"


def _task_source(batch_task: str) -> str:
    p = _REPO / batch_task
    return p.read_text(encoding="utf-8") if p.exists() else ""


def evaluate_table(contract: dict) -> dict:
    prod = contract.get("producer") or {}
    status = prod.get("status")
    transform = prod.get("transform")
    batch_task = prod.get("batch_task")
    registry_producer = status == "producer" and bool(transform) and bool(batch_task)

    src = _task_source(batch_task) if batch_task else ""
    task_exists = bool(batch_task) and (_REPO / batch_task).exists()
    publisher_adopted = task_exists and any(m in src for m in _PUBLISHER_MARKERS)
    standard_cli = task_exists and (_CLI_MARKER in src or _STANDARD_ARGS_MARKER in src)
    pinned = bool(contract.get("writer_schema_pinned"))

    adopted = registry_producer and pinned and publisher_adopted and standard_cli
    # Dishonest pin: claims INV-2 pin but the writer does not go through the publisher.
    integrity_violation = pinned and task_exists and not publisher_adopted

    return {
        "table": contract["table_name"],
        "owner_package": _owner_of(contract),
        "status": status,
        "batch_task": batch_task,
        "task_exists": task_exists,
        "registry_producer": registry_producer,
        "writer_schema_pinned": pinned,
        "publisher_adopted": publisher_adopted,
        "standard_cli": standard_cli,
        "adopted": adopted,
        "integrity_violation": integrity_violation,
    }


def _owner_of(contract: dict) -> str:
    ds = contract.get("drift_summary") or []
    if ds:
        return ds[0].get("owner_package", "SILVER-F062")
    # fall back to the notes / a generic F062 owner
    return "SILVER-F062"


def run(strict: bool = False) -> int:
    reg = load_registry()
    rows = [evaluate_table(reg.table(n)) for n in reg.names()]
    producers = [r for r in rows if r["status"] == "producer"]
    adopters = [r for r in producers if r["adopted"]]
    non_adopters = [r for r in producers if not r["adopted"]]
    violations = [r for r in rows if r["integrity_violation"]]

    summary = {
        "package": "SILVER-F062",
        "producers": len(producers),
        "adopters": len(adopters),
        "non_adopters": len(non_adopters),
        "integrity_violations": len(violations),
        "adoption_pct": round(100.0 * len(adopters) / len(producers), 1) if producers else 0.0,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "F062_adoption.json").write_text(
        json.dumps({"summary": summary, "tables": rows}, indent=2, sort_keys=True), encoding="utf-8")
    (OUT_DIR / "F062_adoption.md").write_text(_render_md(summary, rows), encoding="utf-8")

    print(f"F062 adoption: {summary['adopters']}/{summary['producers']} producers adopted "
          f"({summary['adoption_pct']}%); {summary['integrity_violations']} integrity violation(s)")
    if strict and violations:
        print("INTEGRITY VIOLATIONS (writer_schema_pinned but no publisher route):")
        for v in violations:
            print(f"  - {v['table']} ({v['batch_task']})")
        return 3
    return 0


def _render_md(summary: dict, rows: list[dict]) -> str:
    def _y(b):
        return "yes" if b else "no"
    lines = [
        "# SILVER-F062 -- standard job/publisher protocol adoption",
        "",
        f"Producers: **{summary['producers']}**; adopted: **{summary['adopters']}** "
        f"({summary['adoption_pct']}%); non-adopters: **{summary['non_adopters']}**; "
        f"integrity violations: **{summary['integrity_violations']}**.",
        "",
        "`adopted` = producer.status=producer + INV-2 writer_schema_pinned + write routed through "
        "the SILVER-F015 publisher + standard `--publish-mode` CLI. A producer is NOT adopted merely "
        "because a transform exists; it must migrate its WRITE off the bespoke `df.to_parquet + "
        "put_object` path.",
        "",
        "| table | owner | producer | pinned | publisher | std-cli | ADOPTED |",
        "|---|---|:--:|:--:|:--:|:--:|:--:|",
    ]
    for r in sorted(rows, key=lambda x: (not x["adopted"], x["table"])):
        if r["status"] != "producer":
            continue
        lines.append(
            f"| {r['table']} | {r['owner_package']} | {_y(r['registry_producer'])} | "
            f"{_y(r['writer_schema_pinned'])} | {_y(r['publisher_adopted'])} | "
            f"{_y(r['standard_cli'])} | {'**yes**' if r['adopted'] else 'no'} |"
        )
    lines += [
        "",
        "## Non-adopters (the F062 migration backlog)",
        "",
        "Each remaining producer family migrates behind its own atomic origin/main fix + the one CI "
        "gate (C-BETTER-7). Even defect-free tables migrate; an already-compliant producer is never "
        "rewritten -- only its write path is repointed at the common publisher.",
        "",
    ]
    for r in sorted(rows, key=lambda x: x["table"]):
        if r["status"] == "producer" and not r["adopted"]:
            missing = [k for k in ("registry_producer", "writer_schema_pinned",
                                   "publisher_adopted", "standard_cli") if not r[k]]
            lines.append(f"- `{r['table']}` (owner {r['owner_package']}) -- missing: {', '.join(missing)}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--strict", action="store_true",
                    help="exit 3 if any table has an INTEGRITY violation (dishonest INV-2 pin)")
    args = ap.parse_args()
    return run(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
