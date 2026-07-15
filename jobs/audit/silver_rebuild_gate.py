"""silver_rebuild_gate (SILVER-C001) -- the automated consumer-sync DISPATCHER.

When a silver/gold table is rebuilt, its downstream consumers must be re-synced or the change silently
desyncs the serving stack (a stale pg mirror is masked by the Athena fallback -- it is NOT self-healing).
This job runs the honesty checks after a rebuild and fails closed on any red.

WHY A DISPATCHER, NOT A FIXED CHAIN (Attack 3, finding #1 -- CONFIRMED-BROKEN):
    The draft C001 was ONE fixed chain beginning with `load_pg_numbers --tables <changed>`. That chain
    physically CRASHES (does not no-op) for ~34 of the 43 tables -- every table not in the 7-entry pg mirror:
      * `load_pg_numbers.load_table` -> `reg.get(tid)` KeyErrors for a non-numbers-registry table,
      * `numbers_parity` calls `reg.get(tid)` with no guard -> hard crash,
      * `contract_check`/`_distinct_set` run `FROM <table>` against a mirror that holds only the 7 P1 tables.
    The two marquee CHIRPS repairs and every orphan producer would die at step 1. So C001 branches by
    CONSUMER CLASS (from the F010 registry `consumers` field) and NEVER routes a feature-only table through
    load_pg_numbers/numbers_parity.

    Branch A -- numbers / pg-served tables (the 7 in the pg mirror: psd, wasde, production, esr->esr_compact,
                fred_fx, noaa_oni, gold_weather_z):
        1. pg reload (load_pg_numbers -- DROP+CREATE-in-transaction atomic swap)
        2. numbers_parity --parity (Athena-vs-pg grid, must diff clean)
        3. contract_check (SILVER-C002 -- DISTINCT vocabulary + value-nonnull on the mirror)
        4. cascade_census --diff vs the prior census.json (no NEW un-waived DARK; ATHENA_CALLS==0)
        5. config_check (all 10 lints)
        6. eval-subset -- v4 cascade pins (GATED/judged -> deferred hook unless a runner is injected)

    Branch B -- feature-only tables (the ~34 consumed solely by extractors.py; incl. the projection trio,
                which is footer-checked, NEVER Athena-DISTINCT'd -- INV-3):
        1. feature-extractor probe (probe_source + _check_contract on the table's OWN S3 prefix)
        2. value census V001 (footer-derived null-fraction vs value_columns/min_nonnull_frac -- SILVER-V001)
        3. config_check (the lints referencing the table)

FAIL-CLOSED. One artifact bundle JSON per run. The human-authored bookends (S3/Glue/registry edits) and the
gated bookends (certification edit, image content-check, prod rev) stay manual by design.

CANONICAL-SAFE: this is a VALIDATOR. It reads Glue/S3 (in-VPC) and DROP+CREATEs the pg MIRROR (a derived
cache, not a canonical surface); it never writes canonical S3 / mutates a served Glue table, so it needs no
publish_guard authorization -- there is no publish-capable path here.

IN-VPC EXECUTION (the evidence-build jobdef pattern): RDS is only reachable in-VPC, so a run touching a
Branch-A table submits to Batch on the evidence-build job definition (bakes src/+configs/, injects
EVIDENCE_PG_DSN, Athena on the task role) via the ondemand queue (no Spot reclaim mid-COPY):
    python jobs/submit/submit_batch_silver_rebuild_gate.py --tables silver_wasde,silver_chirps
The exact command is also emitted into the artifact bundle (`in_vpc_submit_command`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

# Batch invokes this by PATH (`python jobs/audit/silver_rebuild_gate.py`), which puts jobs/audit/ -- not the
# repo root -- on sys.path[0], so `import jobs.*` would not resolve. Put the repo root on the path first
# (leviathan.* already resolves via the editable install; jobs.* is a namespace package under the root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# --- branch selection ------------------------------------------------------------------------------------
# The crash-safe pg-mirror allowlist == load_pg_numbers.P1_TABLES (imported so the two can never drift). A
# table outside this set is NEVER handed to load_pg_numbers/numbers_parity (the crash class). Imported
# lazily-safe at module load because jobs.utils.load_pg_numbers is AWS-free at import time.
from jobs.utils.load_pg_numbers import P1_TABLES as _PG_MIRROR_LIST

PG_MIRROR_TABLES = frozenset(_PG_MIRROR_LIST)
# The F010 consumer classes that make a table numbers-served. silver_nasa_power is `both` BUT a PROJECTION
# table excluded from the mirror (size + INV-3), so it is caught by the `table in PG_MIRROR_TABLES` half and
# routes to Branch B -- exactly the shape Attack 3 #1 demands.
_NUMBERS_CONSUMER_CLASSES = frozenset({"numbers_registry", "both"})

BRANCH_A = "A"
BRANCH_B = "B"
BRANCH_UNKNOWN = "unknown"


def select_branch(table: str, *, silver_reg, pg_mirror=PG_MIRROR_TABLES) -> str:
    """Pick the consumer-sync branch for one table from the F010 registry `consumers` field.

    Branch A ONLY when the table is numbers-served AND actually in the pg mirror (so load_pg_numbers can
    reload it without a KeyError). Everything else -- feature-only, projection, orphan, unregistered -- is
    Branch B. An unregistered table returns BRANCH_UNKNOWN (fail-closed: the gate reports it red)."""
    if table not in silver_reg.tables:
        return BRANCH_UNKNOWN
    consumers = (silver_reg.table(table) or {}).get("consumers")
    numbers_class = consumers in _NUMBERS_CONSUMER_CLASSES
    return BRANCH_A if (numbers_class and table in pg_mirror) else BRANCH_B


# --- stage result model ----------------------------------------------------------------------------------
GREEN, RED, SKIPPED = "green", "red", "skipped"


@dataclass
class StageResult:
    name: str
    status: str            # GREEN | RED | SKIPPED
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class TableResult:
    table: str
    branch: str
    stages: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # Fail-closed: a known branch, NO red stage, and at least one stage that actually passed green (an
        # all-skipped table proves nothing and is not a pass). BRANCH_UNKNOWN is never ok.
        if self.branch not in (BRANCH_A, BRANCH_B):
            return False
        if any(s.status == RED for s in self.stages):
            return False
        return any(s.status == GREEN for s in self.stages)

    def to_dict(self) -> dict:
        return {"table": self.table, "branch": self.branch, "ok": self.ok,
                "stages": [s.to_dict() for s in self.stages]}


# --- run context (everything AWS/pg is injected; None in mocked/offline runs) -----------------------------
@dataclass
class GateContext:
    numbers_reg: object                       # numbers registry (load_registry())
    silver_reg: object                        # F010 silver registry
    query_fn: Optional[Callable] = None       # pgnumbers.pg_query (or a mock); None offline
    conn: object = None                       # psycopg connection for pg reload; None offline
    census_asof: str = "2026-02-15"
    prior_census: Optional[dict] = None       # the baseline census.json to --diff against
    eval_runner: Optional[Callable] = None    # inject to actually run the judged eval-subset (else deferred)
    value_census_fn: Optional[Callable] = None  # inject the V001 footer census (else deferred hook)


# ---------------------------------------------------------------------------
# Branch-A stages. Each returns a StageResult and NEVER raises (an exception -> RED so the dispatcher stays
# alive -- the whole point of replacing the crashing fixed chain).
# ---------------------------------------------------------------------------
def stage_pg_reload(table: str, ctx: GateContext) -> StageResult:
    try:
        from jobs.utils import load_pg_numbers
        ts = ctx.numbers_reg.get(table)
        if ctx.conn is None:
            return StageResult("pg_reload", SKIPPED, "no pg connection (offline/dry) -- reload not executed")
        n = load_pg_numbers.load_table(ts, ctx.conn)
        return StageResult("pg_reload", GREEN, f"mirror reloaded {n} rows for {table}")
    except Exception as e:  # noqa: BLE001
        return StageResult("pg_reload", RED, f"{type(e).__name__}: {str(e)[:200]}")


def stage_parity(table: str, ctx: GateContext) -> StageResult:
    """Per-table pg-vs-Athena parity. Runs numbers_parity scoped to this one table (PARITY_TABLES env)."""
    try:
        import importlib
        if ctx.query_fn is None or ctx.conn is None:
            return StageResult("parity", SKIPPED, "no pg backend (offline/dry) -- parity not executed")
        prev = os.environ.get("PARITY_TABLES")
        os.environ["PARITY_TABLES"] = table
        try:
            numbers_parity = importlib.import_module("jobs.utils.numbers_parity")
            rc = numbers_parity.main()
        finally:
            if prev is None:
                os.environ.pop("PARITY_TABLES", None)
            else:
                os.environ["PARITY_TABLES"] = prev
        return StageResult("parity", GREEN if rc == 0 else RED,
                           "clean" if rc == 0 else "parity mismatch/vacuous panel (rc!=0)")
    except Exception as e:  # noqa: BLE001
        return StageResult("parity", RED, f"{type(e).__name__}: {str(e)[:200]}")


def stage_contract_check(table: str, ctx: GateContext) -> StageResult:
    """SILVER-C002 vocabulary + value-nonnull on the reloaded mirror (cross-table; the whole numbers
    vocabulary is cheap). RED on any drift."""
    try:
        from leviathan.graphrag.numbers import contract_check as cch
        if ctx.query_fn is None:
            return StageResult("contract_check", SKIPPED, "no pg query_fn (offline/dry)")
        errs = cch.contract_check(ctx.numbers_reg, query_fn=ctx.query_fn)
        if errs:
            return StageResult("contract_check", RED, f"{len(errs)} vocab drift(s): " + "; ".join(errs[:5]))
        return StageResult("contract_check", GREEN, "vocabulary consistent")
    except Exception as e:  # noqa: BLE001
        return StageResult("contract_check", RED, f"{type(e).__name__}: {str(e)[:200]}")


def _census_diff(prior: Optional[dict], current: dict) -> list[str]:
    """New un-waived DARK legs (present-and-dark now, not dark in the prior baseline) + a non-zero
    ATHENA_CALLS banner. Reused by the stage + directly testable."""
    problems: list[str] = []
    if current.get("banner", {}).get("athena_calls", 0) != 0:
        problems.append(f"ATHENA_CALLS={current['banner']['athena_calls']} (must be 0 -- pg-only census)")
    prior_dark = {(l["contract"], l["node_id"]) for l in (prior or {}).get("legs", [])
                  if l.get("verdict") == "DARK-WITH-REASON"}
    for leg in current.get("legs", []):
        if leg.get("verdict") == "DARK-WITH-REASON" and (leg["contract"], leg["node_id"]) not in prior_dark:
            problems.append(f"NEW dark leg {leg['contract']}/{leg['node_id']} "
                            f"{leg.get('table')}.{leg.get('metric')} -> {leg.get('reason')}")
    return problems


def stage_cascade_census_diff(table: str, ctx: GateContext) -> StageResult:
    try:
        from leviathan.graphrag.numbers import cascade_census as cc
        from leviathan.graphrag.numbers import query as Q
        if ctx.query_fn is None:
            return StageResult("cascade_census_diff", SKIPPED, "no pg query_fn (offline/dry)")
        # The parity stage LEGITIMATELY queries Athena in this same process; the census banner reads
        # the per-process Q.STATS telemetry, so without a reset those calls masquerade as census
        # Athena leaks (ATHENA_CALLS=24 at the first Branch-A fire). Reset makes the banner measure
        # THIS stage only -- the pg-only property the diff asserts.
        Q.reset_stats()
        art = cc.census(asof=ctx.census_asof, query_fn=ctx.query_fn)
        problems = _census_diff(ctx.prior_census, art)
        if problems:
            return StageResult("cascade_census_diff", RED, "; ".join(problems[:6]))
        return StageResult("cascade_census_diff", GREEN,
                           f"no new dark ({art['banner']['dark']} dark total, ATHENA_CALLS=0)")
    except Exception as e:  # noqa: BLE001
        return StageResult("cascade_census_diff", RED, f"{type(e).__name__}: {str(e)[:200]}")


def _run_config_check() -> list[str]:
    """All 10 config_check lints as one aggregated error list (each wrapped so one raising lint that reads a
    mid-edit gitignored config becomes an error string, never a dispatcher crash)."""
    from leviathan.graphrag import config_check as cfg
    checks = [
        ("vocab", cfg.lint_vocab), ("node_silver_map", cfg.check_node_silver_map),
        ("hierarchy", cfg.check_hierarchy), ("geography", cfg.check_geography),
        ("display_names", cfg.check_display_names), ("display_vocab", cfg.check_display_vocab),
        ("cascade_map", cfg.check_cascade_map), ("pin_realizability", cfg.check_pin_realizability),
        ("driver_slices", cfg.check_driver_slices), ("edge_blurbs", cfg.check_edge_blurbs),
    ]
    out: list[str] = []
    for label, fn in checks:
        try:
            for e in (fn() or []):
                out.append(f"{label}: {e}")
        except Exception as e:  # noqa: BLE001
            out.append(f"{label}: RAISED {type(e).__name__}: {str(e)[:150]}")
    return out


def stage_config_check(table: str, ctx: GateContext) -> StageResult:
    try:
        errs = _run_config_check()
        if errs:
            return StageResult("config_check", RED, f"{len(errs)} lint failure(s): " + "; ".join(errs[:5]))
        return StageResult("config_check", GREEN, "all 10 lints pass")
    except Exception as e:  # noqa: BLE001
        return StageResult("config_check", RED, f"{type(e).__name__}: {str(e)[:200]}")


def stage_eval_subset(table: str, ctx: GateContext) -> StageResult:
    """v4 cascade-pin eval subset. The JUDGED run is gated (cost + credit-tracked), so this is a DEFERRED
    hook by default: it records skipped unless an `eval_runner` is injected. The offline pin-realizability
    half already runs inside config_check (check_pin_realizability), so a skip here does not leave the pins
    unchecked -- only the judged strip/citation half is deferred to the gated bookend."""
    if ctx.eval_runner is None:
        return StageResult("eval_subset", SKIPPED,
                           "judged eval-subset is gated (run separately); offline pin-realizability covered "
                           "by config_check.check_pin_realizability")
    try:
        res = ctx.eval_runner(table)
        ok = bool(res.get("ok")) if isinstance(res, dict) else bool(res)
        return StageResult("eval_subset", GREEN if ok else RED, str(res)[:200])
    except Exception as e:  # noqa: BLE001
        return StageResult("eval_subset", RED, f"{type(e).__name__}: {str(e)[:200]}")


# ---------------------------------------------------------------------------
# Branch-B stages (feature-only tables -- NEVER load_pg_numbers/numbers_parity).
# ---------------------------------------------------------------------------
def stage_feature_probe(table: str, ctx: GateContext) -> StageResult:
    """Footer-only feature-extractor probe on the table's OWN S3 prefix (the path extractors.py reads):
    existence + declared required columns present. Uses probe_source (footer stats, no Athena)."""
    try:
        from leviathan.features import extractors
        c = ctx.silver_reg.table(table)
        location = c.get("s3_root")
        if not location:
            return StageResult("feature_probe", RED, "no s3_root in F010 contract")
        probe = extractors.probe_source(table, location)
        if not probe.exists:
            return StageResult("feature_probe", RED, f"no parquet at {location}")
        required = set(ctx.silver_reg.value_columns(table) or [])
        required |= {k for k in (c.get("natural_key") or [])}
        missing = sorted(required - set(probe.columns))
        if missing:
            return StageResult("feature_probe", RED, f"missing required columns {missing}")
        return StageResult("feature_probe", GREEN,
                           f"{probe.num_files} file(s), {probe.num_rows} rows, contract columns present")
    except Exception as e:  # noqa: BLE001
        return StageResult("feature_probe", RED, f"{type(e).__name__}: {str(e)[:200]}")


def stage_value_census(table: str, ctx: GateContext) -> StageResult:
    """SILVER-V001 footer-derived value census: per value_column, non-null fraction >= min_nonnull_frac.
    V001 is a separate R1 package; if its footer census is not yet importable this is a DEFERRED hook
    (skipped, not red -- fail-closed still blocks on the checks that DID run). Inject `value_census_fn` to
    run it here."""
    fn = ctx.value_census_fn
    if fn is None:
        try:  # optional: pick up V001 if it has landed, without a hard dependency on it
            from leviathan.silver import value_census as vc  # type: ignore
            fn = vc.census_table
        except Exception:  # noqa: BLE001
            return StageResult("value_census", SKIPPED,
                               "SILVER-V001 footer census not yet available (inject value_census_fn)")
    try:
        res = fn(table, ctx.silver_reg)
        ok = bool(res.get("ok")) if isinstance(res, dict) else bool(res)
        return StageResult("value_census", GREEN if ok else RED, str(res)[:200])
    except Exception as e:  # noqa: BLE001
        return StageResult("value_census", RED, f"{type(e).__name__}: {str(e)[:200]}")


# --- the two branch pipelines ----------------------------------------------------------------------------
_BRANCH_A_STAGES = (stage_pg_reload, stage_parity, stage_contract_check,
                    stage_cascade_census_diff, stage_config_check, stage_eval_subset)
_BRANCH_B_STAGES = (stage_feature_probe, stage_value_census, stage_config_check)


def run_table(table: str, ctx: GateContext, *, branch_a_stages=_BRANCH_A_STAGES,
              branch_b_stages=_BRANCH_B_STAGES) -> TableResult:
    """Dispatch ONE table down its branch. Branch B never references load_pg_numbers/numbers_parity."""
    branch = select_branch(table, silver_reg=ctx.silver_reg)
    if branch == BRANCH_UNKNOWN:
        return TableResult(table, branch,
                           [StageResult("dispatch", RED, "table not in the F010 silver registry")])
    stages = branch_a_stages if branch == BRANCH_A else branch_b_stages
    return TableResult(table, branch, [st(table, ctx) for st in stages])


# --- the run + artifact bundle ---------------------------------------------------------------------------
def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _submit_command(tables: list[str]) -> str:
    return "python jobs/submit/submit_batch_silver_rebuild_gate.py --tables " + ",".join(tables)


def run_gate(tables: list[str], ctx: GateContext, *, branch_a_stages=_BRANCH_A_STAGES,
             branch_b_stages=_BRANCH_B_STAGES) -> dict:
    """Dispatch every table, fail closed on any red, and build the one artifact bundle for the run."""
    results = [run_table(t, ctx, branch_a_stages=branch_a_stages, branch_b_stages=branch_b_stages)
               for t in tables]
    banner = {
        "tables": len(results),
        "branch_a": sum(1 for r in results if r.branch == BRANCH_A),
        "branch_b": sum(1 for r in results if r.branch == BRANCH_B),
        "unknown": sum(1 for r in results if r.branch == BRANCH_UNKNOWN),
        "red_tables": sum(1 for r in results if not r.ok),
    }
    ok = all(r.ok for r in results) and len(results) > 0
    return {
        "gate": "silver_rebuild_gate",
        "package": "SILVER-C001",
        "run_id": _run_id(),
        "as_of_census": ctx.census_asof,
        "tables": tables,
        "results": [r.to_dict() for r in results],
        "banner": banner,
        "verdict": "PASS" if ok else "FAIL",
        "in_vpc_submit_command": _submit_command(tables),
    }


def _artifact_path(run_id: str):
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    return repo / "reports" / "silver_readiness" / "silver_rebuild_gate" / f"{run_id}.json"


def _build_live_context(tables: list[str], *, census_asof: str) -> GateContext:
    """Wire the real pg backend ONLY when a Branch-A table is present (Branch-B-only runs need no pg -- and
    must not open a mirror connection). Loads the prior census baseline for the --diff."""
    from leviathan.graphrag.numbers.registry import load_registry as load_numbers
    from leviathan.silver import registry as sreg
    numbers_reg = load_numbers()
    silver_reg = sreg.load_registry()

    needs_pg = any(select_branch(t, silver_reg=silver_reg) == BRANCH_A for t in tables)
    query_fn = conn = None
    if needs_pg:
        from leviathan.graphrag.numbers import pgnumbers
        assert os.environ.get("GRAPHRAG_NUMBERS_BACKEND", "").strip().lower() == "pg", \
            "Branch-A tables require GRAPHRAG_NUMBERS_BACKEND=pg (pg-mirror-only)"
        assert os.environ.get("EVIDENCE_PG_DSN"), "Branch-A tables require EVIDENCE_PG_DSN (run in-VPC)"
        assert pgnumbers.enabled(), "Branch-A tables require pgnumbers.enabled()"
        import psycopg
        conn = psycopg.connect(os.environ["EVIDENCE_PG_DSN"], autocommit=True)
        query_fn = pgnumbers.pg_query

    prior = _load_prior_census(census_asof)
    return GateContext(numbers_reg=numbers_reg, silver_reg=silver_reg, query_fn=query_fn, conn=conn,
                       census_asof=census_asof, prior_census=prior)


def _load_prior_census(asof: str) -> Optional[dict]:
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    p = repo / "data" / "cascade_census" / f"as_of_date={asof}" / "census.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="silver_rebuild_gate (SILVER-C001): consumer-sync dispatcher")
    ap.add_argument("--tables", required=True, help="comma-separated table ids that were rebuilt")
    ap.add_argument("--asof", default="2026-02-15", help="census as-of (for the --diff baseline)")
    ap.add_argument("--json", dest="out", default=None, help="artifact bundle path (default: reports/...)")
    a = ap.parse_args(argv)
    tables = [t.strip() for t in a.tables.split(",") if t.strip()]
    if not tables:
        print("FAIL silver_rebuild_gate: no --tables given")
        return 1

    ctx = _build_live_context(tables, census_asof=a.asof)
    bundle = run_gate(tables, ctx)

    from pathlib import Path
    dest = Path(a.out) if a.out else _artifact_path(bundle["run_id"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(bundle, indent=1), encoding="utf-8")

    b = bundle["banner"]
    print(f"silver_rebuild_gate {bundle['run_id']} -> {dest}")
    print(f"  tables={b['tables']} branchA={b['branch_a']} branchB={b['branch_b']} "
          f"unknown={b['unknown']} red={b['red_tables']}  verdict={bundle['verdict']}")
    for r in bundle["results"]:
        if not r["ok"]:
            reds = [s for s in r["stages"] if s["status"] == "red"]
            print(f"  FAIL {r['table']} (branch {r['branch']}): "
                  + "; ".join(f"{s['name']}={s['detail']}" for s in reds))
    return 0 if bundle["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
