#!/usr/bin/env python
"""SILVER-F036: cut the WASDE additive-schema + int64 catalog MIGRATION PLAN (plan-only).

LANE M delivers the F036 catalog change as a *plan artifact*, never an apply (R2/R3 mutate no
catalog -- INV-1; the apply is the gated B-wave). This script is READ-ONLY + AWS-FREE + deterministic.
It:

  1. loads the SILVER-F010 registry contract for ``silver_wasde`` (the live-Glue-matching contract:
     20 catalog columns + 9 hidden-schema additive columns declared with ``glue_type: null``);
  2. synthesises the POST-MIGRATION target contract by resolving each additive column's ``glue_type``
     from its INV-2 ``target_arrow_type`` AND correcting ``months_to_marketing_year_end`` from Glue
     ``int`` (int32) to ``bigint`` (int64) to match the physical parquet (C-WRONG-6);
  3. runs the SILVER-F012 :class:`~leviathan.silver.migrate.CatalogMigrator` in PLAN mode against the
     R0 ``_raw`` live-Glue snapshot (a plan touches nothing; the apply path is never called);
  4. writes, under ``reports/silver_readiness/R2_wasde/``:
       * ``silver_wasde.additive.yaml``  -- the proposed post-migration contract;
       * ``silver_wasde.target.sql``     -- the target DDL rendered from it (bigint + 29 columns);
       * ``f036_migration_plan.json``    -- the exact ``update_table`` plan + diffs + the int64
         reviewed-narrowing flag + the F013 registered-partition SD audit (461 partitions);
       * ``f036_migration_plan.md``      -- a human summary.

The int32->int64 correction is a WIDENING (physical is already int64), but the migrate tool
conservatively classifies EVERY same-base Glue type change as a reviewed migration
(``is_narrowing_change`` is direction-agnostic by design), so the plan surfaces it as an
``unsafe``/reviewed item rather than an auto-applicable additive change. That is the intended
handling: a Glue type change on a REGISTERED-partition table must land WITH the F013 partition-SD
repair, never as a silent ``update_table``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

import yaml  # noqa: E402

from leviathan.common.publish_guard import Authorization, PublishMode  # noqa: E402
from leviathan.silver import ddl as D  # noqa: E402
from leviathan.silver.migrate import CatalogMigrator  # noqa: E402
from leviathan.silver.registry import load_registry  # noqa: E402

TABLE = "silver_wasde"
OUT_DIR = _REPO / "reports" / "silver_readiness" / "R2_wasde"
RAW_SNAPSHOT = (_REPO / "reports" / "silver_readiness" / "20260712_p65impl"
                / "_raw" / f"{TABLE}.get-table.json")

# INV-2 target arrow type -> the Glue catalog type the migration registers.
_ARROW_TO_GLUE = {"string": "string", "bool": "boolean", "int64": "bigint", "float64": "double",
                  "date32[day]": "date"}


class _FrozenGlue:
    """A read-only glue client returning the R0 live snapshot (plan mode never mutates)."""

    def __init__(self, live_table: dict):
        self._live = live_table

    def get_table(self, DatabaseName, Name, **kw):
        if Name != self._live.get("Name"):
            from botocore.exceptions import ClientError
            raise ClientError({"Error": {"Code": "EntityNotFoundException", "Message": Name}},
                              "GetTable")
        return {"Table": self._live}


class _Reg:
    def __init__(self, contract: dict):
        self.tables = {contract["table_name"]: contract}

    def names(self):
        return [TABLE]


def build_target_contract(contract: dict) -> dict:
    """The post-migration contract: additive columns get a concrete glue_type; the int64 fix flips
    months_to_marketing_year_end glue_type int -> bigint. arrow/physical types reflect what the
    F034 producer will write."""
    target = json.loads(json.dumps(contract))  # deep copy
    for col in target["physical_columns"]:
        if col["name"] == "months_to_marketing_year_end":
            col["glue_type"] = "bigint"          # C-WRONG-6 int64 correction (matches physical int64)
        if col.get("glue_type") is None:         # a hidden-schema additive column -> register it
            col["glue_type"] = _ARROW_TO_GLUE.get(col.get("target_arrow_type", "string"), "string")
            col["arrow_type"] = col["target_arrow_type"]
    # the migration resolves the recorded drift.
    target["drift_summary"] = [
        d for d in target.get("drift_summary", [])
        if d["column"] != "months_to_marketing_year_end"
    ]
    target["writer_schema_pinned"] = True
    return target


def cut_plan() -> dict:
    reg = load_registry()
    contract = reg.table(TABLE)
    target = build_target_contract(contract)

    live = json.loads(RAW_SNAPSHOT.read_text(encoding="utf-8"))
    migrator = CatalogMigrator(
        database=live.get("DatabaseName", "leviathan_dev"),
        auth=Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False,
                           readiness=True, reason="F036 plan-only artifact"),
        glue_client=_FrozenGlue(live),
        registry=_Reg(target),
    )
    plan = migrator.plan_table(TABLE)

    live_cols = {c["Name"]: c["Type"] for c in live["StorageDescriptor"]["Columns"]}
    target_cols = [(c["name"], c["glue_type"]) for c in target["physical_columns"]
                   if c.get("glue_type") is not None]
    added = [{"name": n, "type": t} for n, t in target_cols if n not in live_cols]
    changed = [{"name": n, "from": live_cols[n], "to": t}
               for n, t in target_cols if n in live_cols and live_cols[n] != t]
    return {
        "plan": plan.to_dict(),
        "target_contract": target,
        "column_changes": {"added": added, "type_changes": changed},
    }


def render_markdown(plan: dict) -> str:
    p = plan["plan"]
    lines = [
        "# SILVER-F036 -- WASDE additive-schema + int64 catalog migration (PLAN ONLY)",
        "",
        "Read-only plan cut by `scripts/silver/wasde_f036_migration_plan.py` against the R0 live-Glue "
        "snapshot. **No catalog mutation** -- the apply is the gated B-wave, WITH the F013 "
        "registered-partition StorageDescriptor repair.",
        "",
        f"- table: `{p['table']}`  database: `{p['database']}`",
        f"- change_type: **{p['change_type']}**",
        f"- glue call: `{p['glue_call']}`",
        "",
    ]
    lines += _changes_md(plan["column_changes"])
    lines += [
        "## Reviewed items (not auto-applicable)",
        "",
    ]
    if p["unsafe"]:
        for u in p["unsafe"]:
            lines.append(f"- {u}")
        lines += [
            "",
            "> The `months_to_marketing_year_end` `int -> bigint` change is a WIDENING to match the "
            "physical int64 parquet (C-WRONG-6). The migrate tool routes every same-base Glue type "
            "change through review (direction-agnostic), so it is surfaced here rather than "
            "auto-applied -- correct, because a type change on a registered-partition table must "
            "land together with the partition-SD repair below.",
        ]
    else:
        lines.append("_None._")
    audit = p.get("registered_partition_audit") or {}
    lines += [
        "",
        "## Registered-partition audit (F013)",
        "",
        f"- registered: **{audit.get('registered')}**",
        f"- action: {audit.get('action', '(n/a)')}",
        "",
        "The 461 registered `release_date` partitions each carry a StorageDescriptor that will "
        "diverge from the updated table SD; they are repaired via the F013 "
        "`PartitionPublisher` in the same gated wave (never a blind partition mutation).",
        "",
        "Target DDL: `silver_wasde.target.sql`. Proposed contract: `silver_wasde.additive.yaml`.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _changes_md(changes: dict) -> list[str]:
    out = ["## Column adds (9) + type change (1)", ""]
    out += [f"- ADD `{a['name']}` `{a['type']}`" for a in changes["added"]]
    out += [f"- TYPE `{c['name']}` `{c['from']}` -> `{c['to']}` (int64 fix, C-WRONG-6)"
            for c in changes["type_changes"]]
    out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="fail (exit 3) if the on-disk plan differs from a fresh cut")
    args = ap.parse_args()

    out = cut_plan()
    target = out["target_contract"]
    plan_json = json.dumps(out, indent=2, sort_keys=True)
    target_yaml = yaml.safe_dump(target, sort_keys=False, width=100)
    target_ddl = D.render_ddl(target)
    md = render_markdown(out)

    if args.check:
        cur = (OUT_DIR / "f036_migration_plan.json")
        if not cur.exists() or cur.read_text(encoding="utf-8") != plan_json:
            print("F036 migration plan is stale; re-run scripts/silver/wasde_f036_migration_plan.py")
            return 3
        print("F036 migration plan OK")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "f036_migration_plan.json").write_text(plan_json, encoding="utf-8")
    (OUT_DIR / "silver_wasde.additive.yaml").write_text(target_yaml, encoding="utf-8")
    (OUT_DIR / "silver_wasde.target.sql").write_text(target_ddl, encoding="utf-8")
    (OUT_DIR / "f036_migration_plan.md").write_text(md, encoding="utf-8")
    p = out["plan"]
    print("wrote F036 migration plan to %s (change_type=%s, unsafe=%d, additive_diffs=%d)"
          % (OUT_DIR, p["change_type"], len(p["unsafe"]),
             sum(1 for d in p["diffs"] if d.startswith("columns"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
