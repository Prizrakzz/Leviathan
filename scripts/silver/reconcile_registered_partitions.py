"""SILVER-F013 gate artifact: READ-ONLY exact-location reconcile of the live REGISTERED partitions
(ESR 370, esr_compact 10, WASDE 461, model_predictions 14) against the location each partition's key
values imply -- using the R0 ``_raw/<table>.get-partitions.json`` snapshots (no AWS, no mutation).

This proves the F013 acceptance clause "existing ESR/esr_compact/WASDE (370/10/461) partitions
reconcile without mutation": for every registered partition we rebuild the expected S3 location from
its key values + the table root (using the ESR ``as_of_date`` column -> ``as_of=`` DIRECTORY mapping,
:func:`esr_partition_location`, and standard Hive ``key=value`` for the rest) and confirm it matches
the registered location under :func:`leviathan.silver.catalog` normalization. A mismatch is reported,
never repaired here. ASCII only.

Run:  python scripts/silver/reconcile_registered_partitions.py [--baseline 20260712_p65impl]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from leviathan.silver import catalog
from leviathan.silver.partition_publish import esr_partition_location
from leviathan.silver.registry import load_registry

_REPO = Path(__file__).resolve().parents[2]
REGISTERED = ("silver_esr", "silver_esr_compact", "silver_wasde", "silver_model_predictions")


def _expected_location(table: str, root: str, part_key_names: list[str], values: list[str]) -> str:
    if table == "silver_esr":
        cc, my, asof = values
        return esr_partition_location(root, cc, my, asof)
    # standard Hive key=value/ layout
    base = root.rstrip("/")
    for k, v in zip(part_key_names, values):
        base = f"{base}/{k}={v}"
    return base + "/"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="20260712_p65impl")
    args = ap.parse_args()

    report_dir = _REPO / "reports" / "silver_readiness" / args.baseline
    raw_dir = report_dir / "_raw"
    reg = load_registry()

    tables_out = []
    for table in REGISTERED:
        gt = json.loads((raw_dir / f"{table}.get-table.json").read_text(encoding="utf-8"))
        root = catalog._normalize_location(gt["StorageDescriptor"]["Location"])
        part_key_names = [pk["Name"] for pk in gt.get("PartitionKeys", [])]
        parts = json.loads((raw_dir / f"{table}.get-partitions.json").read_text(encoding="utf-8"))
        mismatches = []
        placeholder = 0
        for p in parts["partitions"]:
            values = [str(v) for v in p["Values"]]
            reg_loc = catalog._normalize_location(p["StorageDescriptor"]["Location"])
            exp_loc = catalog._normalize_location(_expected_location(table, root, part_key_names, values))
            if reg_loc != exp_loc:
                # esr_compact registers at the bare commodity dir (no trailing partition segment on
                # some rows) -- treat a registered location that is a prefix-consistent variant as a
                # match only when normalized-equal; otherwise record it.
                mismatches.append({"values": values, "registered": reg_loc, "expected": exp_loc})
        tables_out.append({
            "table": table,
            "registered_count": parts["count"],
            "partition_keys": part_key_names,
            "root": root,
            "exact_match_count": parts["count"] - len(mismatches),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches[:20],
            "reconciles_without_mutation": len(mismatches) == 0,
        })

    out = {
        "package": "SILVER-F013",
        "baseline": args.baseline,
        "mode": "read-only reconcile (R0 get-partitions snapshots; no AWS, no mutation)",
        "tables": tables_out,
    }
    (report_dir / "F013_partition_reconcile.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        f"# SILVER-F013 registered-partition exact-location reconcile ({args.baseline})",
        "",
        "READ-ONLY. Each registered partition's location is rebuilt from its key values + table root "
        "(ESR uses the `as_of_date` column -> `as_of=` directory mapping; the rest use Hive "
        "`key=value/`) and compared under catalog normalization. No mutation.",
        "",
        "| table | registered | exact | mismatch | reconciles |",
        "|---|---|---|---|---|",
    ]
    for t in tables_out:
        lines.append(f"| {t['table']} | {t['registered_count']} | {t['exact_match_count']} | "
                     f"{t['mismatch_count']} | {t['reconciles_without_mutation']} |")
    (report_dir / "F013_partition_reconcile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("F013 reconcile written:", report_dir / "F013_partition_reconcile.json")
    for t in tables_out:
        print(f"  {t['table']}: {t['exact_match_count']}/{t['registered_count']} exact, "
              f"{t['mismatch_count']} mismatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
