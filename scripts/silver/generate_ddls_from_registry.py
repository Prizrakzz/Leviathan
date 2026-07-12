#!/usr/bin/env python
"""SILVER-F011: generate every Athena DDL deterministically from the SILVER-F010 registry.

Retires the first-parquet inference in ``jobs/utils/generate_silver_ddls.py``: the registry
(``configs/silver/tables/<table>.yaml``) is the sole schema authority, so a projected/registered
table can never be flattened by a stale first-file read. Renders via :func:`leviathan.silver.ddl`
in the ``gold_weather_z.sql`` house style, one ``CREATE EXTERNAL TABLE IF NOT EXISTS`` per table.

R1 writes into a NEW directory ``sql/athena/ddl_generated/`` and does NOT overwrite the checked-in
hand DDLs under ``sql/athena/ddl/`` -- the per-table drift between the two is enumerated by
``scripts/silver/f011_ddl_diff_report.py`` and classified in
``reports/silver_readiness/R1_F011_ddl_diff.md``.

READ-ONLY + AWS-FREE + deterministic. No boto3, no Athena, no catalog mutation (INV-1).

Usage:
    python scripts/silver/generate_ddls_from_registry.py --write   # (re)write all DDLs
    python scripts/silver/generate_ddls_from_registry.py           # CHECK: fail (exit 3) on any
                                                                    # drift vs the checked-in tree
    python scripts/silver/generate_ddls_from_registry.py --out-dir sql/athena/ddl_generated
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from leviathan.silver import ddl as D  # noqa: E402
from leviathan.silver.registry import load_registry  # noqa: E402

DEFAULT_OUT = _REPO / "sql" / "athena" / "ddl_generated"


def render_all() -> dict[str, str]:
    """Return ``{table_name: ddl_text}`` for every registry contract, in sorted order."""
    reg = load_registry()
    return {name: D.render_ddl(reg.table(name)) for name in reg.names()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="write the DDLs to --out-dir (default: CHECK-only, fail on drift)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT),
                    help="output directory (default: sql/athena/ddl_generated)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = _REPO / out_dir
    rendered = render_all()

    if args.write:
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in rendered.items():
            (out_dir / f"{name}.sql").write_text(text, encoding="utf-8")
        print("wrote %d DDLs to %s" % (len(rendered), out_dir))
        return 0

    # CHECK mode (default): every rendered DDL must byte-match the checked-in file.
    drift: list[str] = []
    for name, text in rendered.items():
        path = out_dir / f"{name}.sql"
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            drift.append(name)
    if drift:
        print("DDL DRIFT (re-run with --write): " + ", ".join(sorted(drift)))
        return 3
    print("DDL check OK: %d generated DDLs byte-identical under %s" % (len(rendered), out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
