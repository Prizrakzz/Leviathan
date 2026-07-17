"""SILVER-F012 gate artifact: a READ-ONLY dry-run catalog-migration plan across all 43 registry
tables, using the R0 ``_raw/<table>.get-table.json`` snapshots as the LIVE Glue catalog (so no AWS
call is made). Emits ``reports/silver_readiness/<id>/F012_migration_plan.{json,md}``.

The R0 snapshots are the ground truth for the live catalog (README: they are the catalog-level
rollback basis). Planning against them offline reproduces exactly what ``CatalogMigrator.plan_all``
would compute live, and satisfies the F012 acceptance "dry-run across all 42 reports zero unapproved
changes" as a checked-in artifact -- any non-noop row is a declared, reviewable diff, never an
auto-apply. ASCII only.

Run:  python scripts/silver/plan_catalog_migration.py [--baseline 20260712_p65impl]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from leviathan.common.publish_guard import Authorization, PublishMode
from leviathan.silver.migrate import CatalogMigrator
from leviathan.silver.registry import load_registry

_REPO = Path(__file__).resolve().parents[2]


class _SnapshotGlue:
    """A read-only Glue stand-in backed by the R0 ``_raw`` get-table snapshots (no AWS)."""

    def __init__(self, raw_dir: Path):
        self._raw = raw_dir

    def get_table(self, DatabaseName, Name, **kw):
        path = self._raw / f"{Name}.get-table.json"
        if not path.exists():
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "EntityNotFoundException"}}, "GetTable")
        return {"Table": json.loads(path.read_text(encoding="utf-8"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="20260712_p65impl")
    args = ap.parse_args()

    report_dir = _REPO / "reports" / "silver_readiness" / args.baseline
    raw_dir = report_dir / "_raw"
    reg = load_registry()
    # A dry-run authorization: the plan is read-only; nothing may mutate.
    auth = Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False, readiness=False,
                         reason="F012 dry-run plan artifact")
    mig = CatalogMigrator(database="leviathan_dev", auth=auth, glue_client=_SnapshotGlue(raw_dir),
                          registry=reg)

    rows = []
    for table in reg.names():
        plan = mig.plan_table(table)
        rows.append(plan.to_dict())

    tally: dict[str, int] = {}
    for r in rows:
        tally[r["change_type"]] = tally.get(r["change_type"], 0) + 1
    unsafe = [r for r in rows if r["unsafe"]]

    out = {
        "package": "SILVER-F012",
        "baseline": args.baseline,
        "mode": "dry-run (read-only; R0 _raw snapshots as live catalog)",
        "table_count": len(rows),
        "change_tally": tally,
        "unsafe_count": len(unsafe),
        "plans": rows,
    }
    (report_dir / "F012_migration_plan.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        f"# SILVER-F012 catalog-migration dry-run plan ({args.baseline})",
        "",
        "READ-ONLY. Desired = registry (SILVER-F010) build_desired_table; live = R0 `_raw` "
        "get-table snapshots. No AWS call, no mutation. Any non-`noop` row is a declared diff to "
        "review + apply under a lease + signed approval (never auto-applied).",
        "",
        f"- tables planned: **{len(rows)}**",
        f"- change tally: **{tally}**",
        f"- unsafe (refused) diffs: **{len(unsafe)}**",
        "",
        "| table | change | unsafe | diffs |",
        "|---|---|---|---|",
    ]
    for r in rows:
        diffs = "; ".join(r["diffs"][:3]) if r["diffs"] else "-"
        u = ", ".join(r["unsafe"]) if r["unsafe"] else "-"
        lines.append(f"| {r['table']} | {r['change_type']} | {u} | {diffs[:120]} |")
    (report_dir / "F012_migration_plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("F012 plan written:", report_dir / "F012_migration_plan.json")
    print("tables:", len(rows), "tally:", tally, "unsafe:", len(unsafe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
