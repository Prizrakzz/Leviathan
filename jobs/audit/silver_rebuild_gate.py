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

    Branch A -- numbers / pg-served tables (EXACTLY load_pg_numbers.P1_TABLES, imported below and never
                re-listed here -- a hand-copied roster in this docstring drifted silently from 7 to 18):
        1. pg reload (load_pg_numbers -- DROP+CREATE-in-transaction atomic swap)
        2. numbers_parity --parity (Athena-vs-pg grid, must diff clean)
        3. value census V001 (footer-derived null-fraction vs value_columns/min_nonnull_frac -- SILVER-V001;
           SHARED with Branch B, see the ordering note at _BRANCH_A_STAGES)
        4. contract_check (SILVER-C002 -- DISTINCT vocabulary + value-nonnull on the mirror)
        5. cascade_census --diff vs the prior census.json (no NEW un-waived DARK; ATHENA_CALLS==0)
        6. config_check (all 10 lints)
        7. eval-subset -- v4 cascade pins (GATED/judged -> deferred hook unless a runner is injected)

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
import re
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

# FENCE (incident I-1): the image-vs-config preflight. stdlib-only at import time -- boto3/glue is
# imported lazily inside image_stamp.glue_probe, which runs ONLY on the already-failing path, so
# this module stays AWS-free at import exactly as before.
from leviathan.common import image_stamp

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
# WARN is D-PR-5's third status (the plan calls it YELLOW). It exists so a GLOBAL stage -- one whose walk
# covers the whole estate, not just the table under gate -- can report a drift that implicates OTHER tables
# without blocking THIS family's promote. It is deliberately NOT a pass either: `TableResult.ok` needs at
# least one GREEN, so a WARN can never be the only thing a table proved.
GREEN, RED, SKIPPED, WARN = "green", "red", "skipped", "warn"


@dataclass
class StageResult:
    name: str
    status: str            # GREEN | RED | SKIPPED | WARN
    detail: str = ""
    # D-PR-32 (a PRECONDITION of D-PR-5, not a companion). `detail` has always been a truncated summary
    # (`errs[:5]`) and the bundle carried nothing else -- so an error past the fifth was invisible in every
    # downstream reader. Under the split that would be strictly worse than before, because a truncated
    # WARN rides a PASS instead of a promote-blocking RED. `errors` is the FULL, untruncated list;
    # `global_errors` is the subset the split moved off this family's verdict. Nothing is ever dropped.
    errors: list = field(default_factory=list)          # every error the stage produced (untruncated)
    global_errors: list = field(default_factory=list)   # the subset implicating only OTHER tables (WARN)

    def to_dict(self) -> dict:
        # Emitted CONDITIONALLY: a green/skipped stage serializes to exactly the three keys it always did,
        # so every existing bundle reader (the SFN, reports/, dashboards) is untouched by this wave.
        d = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.errors:
            d["error_count"] = len(self.errors)
            d["errors"] = list(self.errors)
        if self.global_errors:
            d["global_error_count"] = len(self.global_errors)
            d["global_errors"] = list(self.global_errors)
        return d


@dataclass
class TableResult:
    table: str
    branch: str
    stages: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # Fail-closed: a known branch, NO red stage, and at least one stage that actually passed green (an
        # all-skipped table proves nothing and is not a pass). BRANCH_UNKNOWN is never ok.
        # WARN passes through UNTOUCHED here -- that is the whole D-PR-5 invariant: the split changes which
        # errors are RED, never what RED means, so a table with a red stage of its own keeps its verdict.
        if self.branch not in (BRANCH_A, BRANCH_B):
            return False
        if any(s.status == RED for s in self.stages):
            return False
        return any(s.status == GREEN for s in self.stages)

    @property
    def warned(self) -> bool:
        """This table promoted OVER a global drift that implicates some other table (D-PR-5)."""
        return any(s.status == WARN for s in self.stages)

    def to_dict(self) -> dict:
        return {"table": self.table, "branch": self.branch, "ok": self.ok, "warn": self.warned,
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
    # D-PR-5 rollback lever. False == the pre-split behaviour EXACTLY (every error of a global stage is
    # RED for every family). Kept as a field, not a constant, so a rollback is an env flip on the existing
    # jobdef rather than an image rebuild -- and so the invariant test can run the same input both ways.
    severity_split: bool = True


# ---------------------------------------------------------------------------
# D-PR-5 -- THE GATE BLAST-RADIUS SEVERITY SPLIT.
#
# THE INCIDENT (2026-08-03, exhibit A). ONE cot vocabulary drift on `brazilian_arabica_coffee` legs redded
# THREE unrelated family gates in one morning. The mechanism is structural, not a tuning miss:
# `contract_check()` (`contract_check.py:215+`) walks the WHOLE estate and returns one flat error list with
# no table parameter anywhere in it; `stage_cascade_census_diff` censuses the whole cascade. Because
# `TableResult.ok` requires "no red stage" and `main()` exits 1 unless the whole bundle is PASS, one global
# drift produces N independent exit-1 gate jobs across N family executions.
#
# WHAT IS RATIFIED (Option 2, NOT Option 1 -- plan Section 3g + decision D-PR-5). The checks still RUN
# globally; only the VERDICT BINDING is partitioned. An error that implicates the family's own gate table
# stays RED exactly as today. An error implicating only OTHER tables becomes WARN, with its full text
# preserved in the bundle. The family that OWNS a drift still goes RED, so a drift is never promoted over
# silently -- it is merely not charged to 24 bystanders.
#
# THE DEFAULT FOR UNATTRIBUTABLE ERRORS IS RED (ratified). The split's purpose is to remove FALSE breadth,
# not to invent narrowness the parser cannot justify. Fail-closed on ambiguity is this estate's doctrine
# everywhere else (BaselineFetchError below; the empty-glob-is-an-ERROR rule at `config_check.py:1614-1621`).
# Stated honestly: every one of the 10 `config_check` lints is unattributable today, so class C's
# `config_check` half is UNKILLED by this item -- see `_config_implicated` and D-PR-29.
#
# TWO FENCES THE FIRST CUT OF THIS ITEM DID NOT HAVE (both fail-closed, both measured 2026-08-04):
#
#   (A) THE ORPHAN FENCE (`gated_tables` / the `owned` arm of `split_by_blast_radius`). "Charge the drift
#       to the family that owns it" is only a safe narrowing WHILE SOME FAMILY OWNS IT. The set the checks
#       WALK is not the set the schedules GATE: `contract_check` walks the numbers registry (19 tables minus
#       the projection trio), while ownership comes from the 26 `configs/silver/dags/*.json` descriptors'
#       `gate_tables` (41 tables). The difference is not empty -- `gold_pattern_records` is in the walk and
#       in NOBODY's `gate_tables`. Without this fence its drift WARNs on all 41 gated tables and reds none:
#       every family promotes over it, exit 0, no alarm, and the only trace is a stdout line in 26 separate
#       container logs. So an error whose implicated tables are ALL unowned is charged to EVERY family.
#
#   (B) THE PROMOTE-BLOCKING FENCE (`blocking=` on `_split_verdict`, used by `stage_cascade_census_diff`).
#       The SFN reads the gate's EXIT CODE and nothing else (`step_functions/main.tf:38-40`), and
#       `Gate.Next = "Promote"` is unconditional -- so exit 0 PUBLISHES CANONICAL. The state machine then
#       runs [Reconcile] = `advance_rolling_census`, which re-runs `cascade_census.main` whose criterion is
#       the ABSOLUTE un-waived DARK count (`cascade_census.py:623`, `return 1 if dark else 0`), NOT the
#       baseline diff this gate applies. A census WARN therefore promoted canonical and THEN failed the
#       execution -- alerting with "Canonical left untouched (INV-6)" about canonical it had just touched.
#       The exit code and the promote decision must come from the SAME verdict, so a census drift that the
#       Reconcile step will refuse is RED here, on every family, even when it names another table.
# ---------------------------------------------------------------------------
_TABLE_TOKEN = r"[a-z][a-z0-9_]*"
# `{tid}: ...` -- check_metric_vocabulary's prefix (`contract_check.py:96,100,106`). The country/slug
# families prefix `{contract}/{did}: ` instead, and the `/` makes this pattern miss them by construction:
# a leg id is not a table id and must never be read as one.
_ERR_TABLE_PREFIX_RE = re.compile(r"^(%s):\s" % _TABLE_TOKEN)
# `... of {table}` -- every C002 family names its implicated table this way: `of {phys}` for the metric
# families (`:96,106`), `of {table}` for the country/slug families (`:166,207`).
_ERR_TABLE_OF_RE = re.compile(r"\bof (%s)\b" % _TABLE_TOKEN)
# `[table=silver_x]` / `[table=silver_x,silver_y]` -- the OPT-IN marker a config_check lint may emit to make
# itself attributable. Nothing emits it today (see _config_implicated).
_ERR_TABLE_MARKER_RE = re.compile(r"\[table=(%s(?:,%s)*)\]" % (_TABLE_TOKEN, _TABLE_TOKEN))


def implicated_tables(error: str) -> frozenset:
    """The table id(s) a contract_check error string implicates. Empty == unattributable (-> RED).

    Parses the two shapes `contract_check` actually emits rather than guessing: the `{tid}: ` prefix and
    every `of {table}`. Over-matching here is SAFE BY DIRECTION -- a spurious extra table can only widen
    the implicated set, i.e. make more families RED, which is the pre-split behaviour. Under-matching is
    the dangerous direction and is why the fallback for "no token found" is RED, not WARN."""
    out = set()
    m = _ERR_TABLE_PREFIX_RE.match(error or "")
    if m:
        out.add(m.group(1))
    out.update(_ERR_TABLE_OF_RE.findall(error or ""))
    return frozenset(out)


def _config_implicated(error: str) -> frozenset:
    """The table(s) a `_run_config_check` lint error implicates -- EMPTY for every lint shipping today.

    RATIFIED (D-PR-5): `_run_config_check` emits `f"{label}: {e}"` and several lints (`vocab`, `hierarchy`,
    `display_names`, `edge_blurbs`) may not reference a silver table at all. Reusing `implicated_tables`
    here would read the LINT LABEL as a table id ("vocab: ...") and silently demote a real estate-wide
    failure to WARN -- the exact false narrowness the ratified decision forbids. So attribution here is
    OPT-IN ONLY: a lint that wants to be table-scoped must say so with an explicit `[table=...]` marker.

    This is the seam D-PR-29 names, and it deliberately does NOT resolve D-PR-29: until a lint emits the
    marker, the D-PR-6 unfenced-`not_covered` detector -- landing in `_run_config_check` -- reds every
    family, so class C's config half stays UNKILLED and the plan's census table says so."""
    out = set()
    for group in _ERR_TABLE_MARKER_RE.findall(error or ""):
        out.update(t for t in group.split(",") if t)
    return frozenset(out)


def _gate_table_aliases(table: str, numbers_reg=None) -> frozenset:
    """Every id an error string may legitimately use for THIS gate table.

    The numbers stack carries agent-facing ids and physical ids for the same table (`silver_esr` serves
    from `silver_esr_compact` -- `contract_check._physical`, `:48-50`), and the checks do NOT agree on
    which to print: the metric families print the physical table (`contract_check.py:96,106`), the
    cascade families print the mapped agent id off the cascade_map row (`:166,207`).

    Measured, so the fence is not oversold: today every metric-family error ALSO carries the agent id in
    its `{tid}: ` prefix and every `cascade_map` row names an agent id (`cascade_map.yaml:238` is
    `table: silver_esr`), so attribution would survive on the prefix alone. This exists for the emit that
    has only the physical name -- which would otherwise resolve to nobody and CLEAR the one family that
    owns the drift. A false clear is the only direction of this split that can hurt. Never raises: a
    registry shim or a mid-edit registry degrades to the identity alias, which errs toward RED."""
    out = {table}
    try:
        ts = numbers_reg.get(table)
        phys = getattr(ts, "athena_table", None) or getattr(ts, "id", None)
        if phys:
            out.add(str(phys))
    except Exception:  # noqa: BLE001 -- not a numbers table (Branch B), a shim, or a mid-edit registry
        pass
    try:
        for tid in (getattr(numbers_reg, "tables", None) or ()):
            spec = numbers_reg.get(tid)
            if (getattr(spec, "athena_table", None) or tid) == table:
                out.add(str(tid))
    except Exception:  # noqa: BLE001
        pass
    return frozenset(out)


# The family dag descriptors -- the ONLY place ownership is declared. A table is "owned" iff some
# schedule's `gate_tables` lists it, because that is exactly the set of tables for which SOME family's
# gate can go RED. `_rendered/` is deliberately out of reach: `glob` here is non-recursive, so the
# rendered `*.input.json` execution payloads are never mistaken for descriptors.
_DAG_DESCRIPTOR_DIR = _REPO_ROOT / "configs" / "silver" / "dags"
_GATED_CACHE: list = []   # one-slot memo for the DEFAULT dir only (a gate run is a one-shot process)


def gated_tables(descriptor_dir=None) -> Optional[frozenset]:
    """Every table that SOME family's gate would go RED for: the union of `gate_tables` over the dag
    descriptors. Returns None when ownership cannot be established at all (see fence (A) above).

    None is NOT "no orphans" -- it is "nobody owns anything", which `split_by_blast_radius` reads as
    fail-closed and charges every error to the table under gate. An individually unreadable descriptor
    is SKIPPED rather than voiding the whole map: skipping only makes ITS tables look orphaned, which
    errs toward RED for those tables alone instead of redding the estate over one mid-edit file.
    Never raises -- an ownership fence that can crash is a fence that can be argued away."""
    if descriptor_dir is None and _GATED_CACHE:
        return _GATED_CACHE[0]
    d = Path(descriptor_dir) if descriptor_dir else _DAG_DESCRIPTOR_DIR
    out: set = set()
    try:
        paths = sorted(d.glob("*.json"))
    except Exception:  # noqa: BLE001 -- unreadable/absent configs tree -> ownership unknown
        return None
    for p in paths:
        if p.name.endswith(".schema.json"):   # the descriptor SCHEMA, not a descriptor
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- mid-edit/truncated descriptor: its tables read as orphans
            continue
        for t in (doc.get("gate_tables") or ()):
            if t:
                out.add(str(t))
    owned = frozenset(out) or None
    if descriptor_dir is None:
        _GATED_CACHE.append(owned)
    return owned


def _owned_tables(ctx) -> Optional[frozenset]:
    """`gated_tables()` widened by every alias each gated table answers to.

    Same reason `_gate_table_aliases` exists on the other side of the comparison: one table carries an
    agent id and a physical id (`silver_esr` serves from `silver_esr_compact`) and the checks do not
    agree on which they print. Widening the OWNED set can only make FEWER errors look orphaned, i.e. it
    can only avoid a false estate-wide RED -- it can never clear a real orphan."""
    gated = gated_tables()
    if not gated:
        return None
    reg = getattr(ctx, "numbers_reg", None)
    out = set(gated)
    for t in gated:
        out |= _gate_table_aliases(t, reg)
    return frozenset(out)


def split_by_blast_radius(items, aliases, owned=None) -> tuple:
    """Partition `(error_text, implicated_tables)` pairs into (mine, others_only).

    `mine` (-> RED) is every error that
      * implicates one of THIS table's aliases, or
      * implicates NOTHING parseable (the ratified fail-closed default for unattributable errors), or
      * implicates ONLY ORPHANS -- tables no family's `gate_tables` lists, so no family would ever red
        for it and moving it off this verdict moves it onto nobody's (fence (A) above).

    `owned` is the ownership map from `_owned_tables`; None means it could not be read, which is read as
    "nobody owns anything" and charges every error to this table. An error naming an owned table AND an
    orphan is NOT orphaned: the owning family still reds, so the drift is not promoted over silently."""
    alias_set = set(aliases)
    own = None if owned is None else set(owned)
    mine, others = [], []
    for text, implicated in items:
        imp = set(implicated or ())
        orphan = (own is None) or not (imp & own)
        (mine if (not imp or (imp & alias_set) or orphan) else others).append(text)
    return mine, others


def _split_verdict(name: str, table: str, ctx: GateContext, items, *, noun: str,
                   blocking: bool = False) -> StageResult:
    """Build the StageResult for a GLOBAL stage that produced at least one error, applying D-PR-5.

    INVARIANT: this function can only ever turn a RED into a WARN, and only when NO error implicates
    `table`. It never turns anything into a GREEN, and it is never reached when `items` is empty -- so a
    table whose own stages are red keeps a bit-identical verdict with the split on or off.

    `blocking=True` marks a stage whose drift a LATER state of the SAME SFN execution will refuse on an
    ABSOLUTE criterion (fence (B) above). For such a stage the others-only case stays RED: the exit code
    and the promote decision must come from ONE verdict, so the gate never publishes canonical into a
    pipeline that is about to fail. The attribution is not lost -- `global_errors` and the detail still
    say the drift belongs to another table -- only the VERDICT stays fail-closed."""
    texts = [t for t, _ in items]
    if not getattr(ctx, "severity_split", True):
        # ROLLBACK PATH: the pre-split VERDICT exactly -- every error RED for every family. The detail
        # string is not byte-identical to the old one for cascade_census_diff (which had no count prefix
        # and truncated at 6, `:230` pre-wave); all three global stages now share one summary shape, and
        # the untruncated truth lives in `errors` either way.
        return StageResult(name, RED, f"{len(texts)} {noun}: " + "; ".join(texts[:5]), errors=texts)
    aliases = _gate_table_aliases(table, getattr(ctx, "numbers_reg", None))
    mine, others = split_by_blast_radius(items, aliases, _owned_tables(ctx))
    if mine:
        detail = f"{len(mine)} {noun}: " + "; ".join(mine[:5])
        if others:
            detail += f" (+{len(others)} global_drift on other tables)"
        return StageResult(name, RED, detail, errors=texts, global_errors=others)
    if blocking:
        detail = (f"global_drift (PROMOTE-BLOCKING): {len(others)} {noun} on other tables, none "
                  f"implicating {table}, but [Reconcile] refuses this run on an ABSOLUTE criterion -- "
                  f"promoting would publish canonical into a failing execution: "
                  + "; ".join(others[:5]))
        return StageResult(name, RED, detail, errors=texts, global_errors=others)
    detail = (f"global_drift: {len(others)} {noun} on other tables, none implicating {table}: "
              + "; ".join(others[:5]))
    return StageResult(name, WARN, detail, errors=texts, global_errors=others)


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
    vocabulary is cheap). RED on a drift implicating THIS table, on an unattributable one, or on one
    naming only tables NO family gates (fence (A)); WARN on one implicating only other OWNED tables
    (D-PR-5). The walk itself is unchanged -- global as before -- so nothing stops being detected."""
    try:
        from leviathan.graphrag.numbers import contract_check as cch
        if ctx.query_fn is None:
            return StageResult("contract_check", SKIPPED, "no pg query_fn (offline/dry)")
        errs = cch.contract_check(ctx.numbers_reg, query_fn=ctx.query_fn)
        if not errs:
            return StageResult("contract_check", GREEN, "vocabulary consistent")
        return _split_verdict("contract_check", table, ctx,
                              [(e, implicated_tables(e)) for e in errs], noun="vocab drift(s)")
    except Exception as e:  # noqa: BLE001
        # UNATTRIBUTABLE BY CONSTRUCTION: an exception is not an error STRING, so there is no leg and no
        # table to charge it to -- and a check that crashed proved nothing about ANY table. RED (ratified).
        detail = f"{type(e).__name__}: {str(e)[:200]}"
        return StageResult("contract_check", RED, detail, errors=[detail])


def _census_diff_attributed(prior: Optional[dict], current: dict) -> list:
    """`_census_diff` with each problem paired to the table(s) it implicates (D-PR-5).

    Attribution is read straight off the leg record (`cascade_census._leg_record`, `:224-228` -- the leg
    carries its own `table`), never re-parsed out of the formatted string. The ATHENA_CALLS banner is a
    property of the census RUN, not of any leg, so it is deliberately unattributable -> RED everywhere.

    WHY THIS STAGE IS NOT OPTIONAL (plan Section 2.5). `prior_dark` is EMPTY estate-wide today: ten monthly
    families still carry a 2026-07-16..18 baseline vintage with `dark: 0`. So the FIRST dark leg introduced
    anywhere reds EVERY family at once -- exhibit A's blast radius reproduced in a second stage."""
    problems: list = []
    if current.get("banner", {}).get("athena_calls", 0) != 0:
        problems.append((f"ATHENA_CALLS={current['banner']['athena_calls']} (must be 0 -- pg-only census)",
                         frozenset()))
    prior_dark = {(l["contract"], l["node_id"]) for l in (prior or {}).get("legs", [])
                  if l.get("verdict") == "DARK-WITH-REASON"}
    for leg in current.get("legs", []):
        if leg.get("verdict") == "DARK-WITH-REASON" and (leg["contract"], leg["node_id"]) not in prior_dark:
            tbl = leg.get("table")
            problems.append((f"NEW dark leg {leg['contract']}/{leg['node_id']} "
                             f"{tbl}.{leg.get('metric')} -> {leg.get('reason')}",
                             frozenset({str(tbl)}) if tbl else frozenset()))
    return problems


def _census_diff(prior: Optional[dict], current: dict) -> list[str]:
    """New un-waived DARK legs (present-and-dark now, not dark in the prior baseline) + a non-zero
    ATHENA_CALLS banner. The text-only view of `_census_diff_attributed` (unchanged contract)."""
    return [text for text, _ in _census_diff_attributed(prior, current)]


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
        problems = _census_diff_attributed(ctx.prior_census, art)
        if not problems:
            return StageResult("cascade_census_diff", GREEN,
                               f"no new dark ({art['banner']['dark']} dark total, ATHENA_CALLS=0)")
        # PROMOTE-BLOCKING (fence (B)). This is the ONE global stage whose finding the same execution
        # re-judges downstream, and on a WIDER criterion: [Reconcile] runs advance_rolling_census ->
        # cascade_census.main, which exits 1 on the ABSOLUTE un-waived DARK count while this stage only
        # diffs against the baseline. On the scheduled path the two criteria coincide exactly, because
        # advance_rolling_census refuses to enshrine a dirty census as a rolling baseline
        # (advance_rolling_census.py: `if rc != 0: return rc`, BEFORE the upload) -- so every
        # --baseline-uri baseline is dark-free, every dark leg is a NEW dark leg, and "this stage fires"
        # is precisely "Reconcile will fail". Demoting it to WARN bought exit 0 -> [Promote] ->
        # canonical published -> [Reconcile] fails -> FailNotify, i.e. the alarm still fires, the
        # baseline still does not advance, and the loss is the fail-closed protection plus the truth of
        # the alert's own "Canonical left untouched (INV-6)". So it stays RED for everyone.
        return _split_verdict("cascade_census_diff", table, ctx, problems, noun="census problem(s)",
                              blocking=True)
    except Exception as e:  # noqa: BLE001
        # Unattributable (see stage_contract_check) -> RED.
        detail = f"{type(e).__name__}: {str(e)[:200]}"
        return StageResult("cascade_census_diff", RED, detail, errors=[detail])


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
    """All 10 repo lints. Runs through the SAME D-PR-5 partitioner as the other two global stages, but with
    the strict `_config_implicated` attributor -- so with today's lint strings every error is unattributable
    and this stage stays RED estate-wide, exactly as the ratified decision states."""
    try:
        errs = _run_config_check()
        if not errs:
            return StageResult("config_check", GREEN, "all 10 lints pass")
        return _split_verdict("config_check", table, ctx,
                              [(e, _config_implicated(e)) for e in errs], noun="lint failure(s)")
    except Exception as e:  # noqa: BLE001
        detail = f"{type(e).__name__}: {str(e)[:200]}"
        return StageResult("config_check", RED, detail, errors=[detail])


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
#
# stage_value_census is the one SHARED stage: since the 2026-08-01 Branch-A ratification it runs on BOTH
# branches (see the ordering note at _BRANCH_A_STAGES). Nothing in it is Branch-B-specific -- it consumes
# `table` plus the F010 contract from ctx.silver_reg and reads S3 parquet FOOTERS; it never touches
# ctx.conn, ctx.query_fn or ctx.numbers_reg, and value_census.sample_groups already handles every
# partition_mode (flat / projected / registered / partitioned), which is what a Branch-A table like
# silver_futures_eod (partition_mode: registered, keys leviathan_slug + trade_year) needs. Verified before
# the append; NO adaptation was required.
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
        # Hive partition-key columns (commodity= for silver_nass_crop_progress, release_date= for
        # silver_wasde) are materialized in the S3 PATH, NEVER in the parquet FOOTER schema that
        # probe.columns reflects -- so a partitioned table whose natural_key includes its partition key
        # would false-RED here ("missing required columns ['commodity']"). Declared partition keys count
        # as PRESENT (satisfied from the contract / path-materialized); only genuinely-missing IN-FILE
        # columns stay RED (e.g. silver_wasde's additive F036 columns lagging on pre-2026-06 partitions).
        pk = {k.get("name") for k in (c.get("partition_keys") or [])}
        path_materialized = sorted((required & pk) - set(probe.columns))
        missing = sorted((required - pk) - set(probe.columns))
        if missing:
            return StageResult("feature_probe", RED, f"missing required columns {missing}")
        detail = f"{probe.num_files} file(s), {probe.num_rows} rows, contract columns present"
        if path_materialized:
            detail += f"; +{len(path_materialized)} partition-key column(s) path-materialized"
        return StageResult("feature_probe", GREEN, detail)
    except Exception as e:  # noqa: BLE001
        return StageResult("feature_probe", RED, f"{type(e).__name__}: {str(e)[:200]}")


def stage_value_census(table: str, ctx: GateContext) -> StageResult:
    """SILVER-V001 footer-derived value census: per value_column, non-null fraction >= min_nonnull_frac
    + vintage adequacy (waiver-aware). Wired to the REAL V001 runner (jobs.audit.value_census.
    census_one_table) -- the old fallback referenced a `census_table` symbol that never existed, so
    every Branch-B run silently SKIPPED this stage (B3 phase-0 finding B3-03; the floor was only ever
    enforced by the standalone runner). Inject `value_census_fn` to override (tests/offline).

    RUNS ON BOTH BRANCHES since 2026-08-01 (the silver_futures_eod Branch-A ratification). Reads the
    F010 contract + S3 footers only, so it is deliberately NOT gated on ctx.query_fn/ctx.conn the way
    the pg stages are: an offline Branch-A run skips every mirror stage and still measures the floor."""
    fn = ctx.value_census_fn
    if fn is None:
        try:
            from jobs.audit.value_census import census_one_table  # the real V001 runner (S3 footer reads)
        except Exception:  # noqa: BLE001 -- only a broken tree lands here; never silently green
            return StageResult("value_census", SKIPPED,
                               "SILVER-V001 runner unimportable (inject value_census_fn)")

        def fn(t, silver_reg):  # adapter: gate contract-in, {ok,...} out
            result, _artifact = census_one_table(silver_reg.table(t))
            return {"ok": result.passed, "gate_rows": len(result.gate_rows),
                    "warn_rows": len(result.warn_rows), "files_sampled": result.files_sampled,
                    "first_gate": result.gate_rows[0].detail if result.gate_rows else None}
    try:
        res = fn(table, ctx.silver_reg)
        ok = bool(res.get("ok")) if isinstance(res, dict) else bool(res)
        return StageResult("value_census", GREEN if ok else RED, str(res)[:200])
    except Exception as e:  # noqa: BLE001
        return StageResult("value_census", RED, f"{type(e).__name__}: {str(e)[:200]}")


# --- the two branch pipelines ----------------------------------------------------------------------------
# BRANCH-A STAGE ORDER, and why the V001 census sits THIRD.
#
# The list is ordered by WIDENING SCOPE -- the convention the module docstring's own numbering already
# encodes. pg_reload and parity speak about THIS TABLE; contract_check is cross-table (the whole numbers
# vocabulary on the mirror -- "the whole numbers vocabulary is cheap"); cascade_census_diff is the whole
# cascade; config_check is all 10 repo lints; eval_subset is the judged deck. Branch B is the same shape
# at its own scale: feature_probe (this table's bytes exist and carry its columns) -> value_census (this
# table's bytes are POPULATED) -> config_check. So the census belongs in the per-table block, after the
# reload+parity that establish WHICH bytes are under test and ahead of the three cross-table stages --
# and a cheap, table-specific red should not be paid for behind a full cascade census.
#
# WHY IT IS HERE AT ALL (BRANCH-A RATIFICATION, 2026-08-01). Ratifying silver_futures_eod into Branch A
# moved it OFF the Branch-B pipeline -- and Branch B held the only populatedness assertion in either
# branch, because Branch A had none. Nothing else in Branch A can stand in for it: pg_reload counts ROWS,
# parity compares pg against Athena (identically-wrong on both backends is a clean PASS -- it proves the
# mirror, not the data), and contract_check's value-nonnull is the C002 check over the numbers registry's
# declared metrics, not the F010 min_nonnull_frac floor. Without this line, ratification would have
# silently DELETED the V001 floor for every table it promotes. Appending it discharges the memo's Step 3.
#
# MEASURED for silver_futures_eod, 2026-08-01: settle non-null 445,888 / 455,882 = 0.9781 against the
# contract's min_nonnull_frac 0.5 (configs/silver/tables/silver_futures_eod.yaml).
_BRANCH_A_STAGES = (stage_pg_reload, stage_parity, stage_value_census, stage_contract_check,
                    stage_cascade_census_diff, stage_config_check, stage_eval_subset)
_BRANCH_B_STAGES = (stage_feature_probe, stage_value_census, stage_config_check)


def run_table(table: str, ctx: GateContext, *, branch_a_stages=_BRANCH_A_STAGES,
              branch_b_stages=_BRANCH_B_STAGES) -> TableResult:
    """Dispatch ONE table down its branch. Branch B never references load_pg_numbers/numbers_parity."""
    branch = select_branch(table, silver_reg=ctx.silver_reg)
    if branch == BRANCH_UNKNOWN:
        # FENCE (I-1), belt-and-braces. The old detail was "table not in the F010 silver registry",
        # which names the CONFIG and sent the whole 2026-07-24..31 RCA to a file that was fine. Any
        # caller that reaches run_gate() without going through main()'s preflight still gets the
        # honest sentence: it names the IMAGE, its provenance and the remedy.
        return TableResult(table, branch,
                           [StageResult("dispatch", RED, image_stamp.dispatch_detail(table))])
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
        # D-PR-5 acceptance: a PASSing run that rode over somebody else's drift must SAY SO in the bundle.
        # `global_drift` counts WARN stages (the drift events), `warn_tables` the tables that carry one.
        "warn_tables": sum(1 for r in results if r.warned),
        "global_drift": sum(1 for r in results for s in r.stages if s.status == WARN),
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
        # FENCE (I-1): every artifact bundle now records WHICH CONTAINER produced it. The 2026-07-24
        # bundles could not answer that question, so nobody could tell a config fault from an image
        # fault by reading them.
        "image": _image_block(),
        "verdict": "PASS" if ok else "FAIL",
        "in_vpc_submit_command": _submit_command(tables),
    }


def _image_block(facts: Optional[dict] = None) -> dict:
    """The provenance block embedded in every artifact bundle (never raises)."""
    try:
        f = facts if facts is not None else image_stamp.image_facts()
    except Exception as e:  # noqa: BLE001
        return {"manifest_present": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    return {"manifest_present": f["manifest_present"], "git_commit": f["git_commit"],
            "build_time_utc": f["build_time_utc"], "age_days": f["age_days"],
            "silver_tables_count": f["silver_tables_count"],
            "silver_tables_fp": f["silver_tables_fp"]}


def _preflight_image_config(tables: list[str], **kw) -> dict:
    """FENCE (I-1). Can THIS CONTAINER honour THIS ask at all?

    Thin seam over ``image_stamp.preflight`` so tests can inject a registry loader / manifest
    loader / Glue probe with no AWS and no filesystem surgery. Never raises: a fence that can
    crash is a fence that can be argued away."""
    return image_stamp.preflight(tables, **kw)


def _preflight_bundle(tables: list[str], census_asof: str, pre: dict) -> dict:
    """The artifact bundle for a run that never got past the preflight.

    Deliberately the SAME SHAPE run_gate() emits (gate/package/run_id/results/banner/verdict), so
    every existing reader -- the SFN, the reports/ tree, any dashboard -- keeps working. What is
    ADDED is the pair of facts the 2026-07-24 bundles could not answer: which container produced
    this, and WHY it refused (``verdict_reason``)."""
    results = [TableResult(t, BRANCH_UNKNOWN, [StageResult("dispatch", RED, detail)])
               for t, detail in pre["red_tables"]]
    banner = {
        "tables": len(results),
        "branch_a": 0,
        "branch_b": 0,
        "unknown": len(results),
        "red_tables": len(results),
        # Same keys run_gate() emits, so a reader never has to branch on which path built the bundle.
        "warn_tables": 0,
        "global_drift": 0,
    }
    return {
        "gate": "silver_rebuild_gate",
        "package": "SILVER-C001",
        "run_id": _run_id(),
        "as_of_census": census_asof,
        "tables": tables,
        "results": [r.to_dict() for r in results],
        "banner": banner,
        "image": _image_block(pre.get("image")),
        "verdict": "FAIL",
        "verdict_reason": pre.get("reason", "preflight_failed"),
        "preflight": {"ok": False, "reason": pre.get("reason"),
                      "lines": list(pre.get("lines") or []),
                      "glue_probes": pre.get("probes") or {}},
        "in_vpc_submit_command": _submit_command(tables),
    }


def _artifact_path(run_id: str):
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    return repo / "reports" / "silver_readiness" / "silver_rebuild_gate" / f"{run_id}.json"


def _build_live_context(tables: list[str], *, census_asof: str,
                        baseline_uri: Optional[str] = None) -> GateContext:
    """Wire the real pg backend ONLY when a Branch-A table is present (Branch-B-only runs need no pg -- and
    must not open a mirror connection). Loads the prior census baseline for the --diff (from S3 when
    ``baseline_uri`` is set -- FAIL CLOSED on fetch error -- else the image-baked snapshot)."""
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

    prior = _load_prior_census(census_asof, baseline_uri=baseline_uri)
    return GateContext(numbers_reg=numbers_reg, silver_reg=silver_reg, query_fn=query_fn, conn=conn,
                       census_asof=census_asof, prior_census=prior,
                       severity_split=_severity_split_enabled())


def _severity_split_enabled() -> bool:
    """D-PR-5's rollback lever, read from the environment so a rollback is a jobdef env flip -- NOT an
    image rebuild. Unset == ON (the ratified behaviour); `0/off/false/no` == the pre-split "every global
    error is RED for every family"."""
    return os.environ.get("GATE_SEVERITY_SPLIT", "1").strip().lower() not in ("0", "off", "false", "no")


class BaselineFetchError(RuntimeError):
    """A scheduled rolling-baseline census (--baseline-uri / CENSUS_BASELINE_S3) could not be fetched or
    parsed. The gate FAILS CLOSED on this and NEVER silently falls back to the image-baked snapshot: a
    stale or wrong baseline can mask a regression and let the census --diff pass a bad rebuild."""


def _s3_client():
    """boto3 S3 client factory. Indirection so tests can stub S3 with no boto3/network dependency, and so
    module import stays AWS-free (boto3 is imported lazily here, never at module load)."""
    import boto3
    return boto3.client("s3")


def _load_census_from_s3(uri: str) -> dict:
    """Fetch a rolling-baseline census.json from S3 (read-only get_object) for the scheduled gate.

    FAIL CLOSED (raise BaselineFetchError) on a malformed URI, any get_object error, or unparseable JSON.
    A scheduled gate must never run against a stale/absent baseline; falling back to the image-baked
    snapshot here would let a regression pass the census --diff. ASCII-only messages."""
    if not uri.startswith("s3://"):
        raise BaselineFetchError(f"baseline-uri must be an s3://bucket/key URI, got: {uri!r}")
    bucket, _, key = uri[len("s3://"):].partition("/")
    if not bucket or not key:
        raise BaselineFetchError(f"baseline-uri is missing a bucket or key: {uri!r}")
    try:
        body = _s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as e:  # noqa: BLE001 -- fail closed on ANY S3 error (auth/network/404/...)
        raise BaselineFetchError(
            f"baseline census fetch failed for {uri}: {type(e).__name__}: {str(e)[:200]}") from e
    try:
        return json.loads(body.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise BaselineFetchError(
            f"baseline census at {uri} is not valid JSON: {type(e).__name__}: {str(e)[:200]}") from e


def _load_prior_census(asof: str, baseline_uri: Optional[str] = None) -> Optional[dict]:
    """Load the baseline census.json to --diff against.

    When ``baseline_uri`` (an s3://bucket/key) is set -- the scheduled rolling-baseline path (A-W3) --
    fetch it from S3 and FAIL CLOSED on any error (see _load_census_from_s3); never fall back to the
    image-baked snapshot. When unset (default), load the image-baked
    ``data/cascade_census/as_of_date={asof}/census.json`` exactly as before (returns None if the file is
    absent or unparseable -- unchanged, backward-compatible behavior)."""
    if baseline_uri:
        return _load_census_from_s3(baseline_uri)
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    p = repo / "data" / "cascade_census" / f"as_of_date={asof}" / "census.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def _print_stage_errors(label: str, table: str, stage: dict) -> None:
    """Print EVERY error a stage produced, one per line, to stdout.

    D-PR-32 says the full text is "preserved, never silently dropped" -- but on the SCHEDULED path the
    bundle is not a delivery mechanism. All 26 rendered gate commands
    (`configs/silver/dags/_rendered/*.input.json`) invoke the gate with NO `--json`, so the bundle is
    written to `reports/silver_readiness/...` INSIDE the Batch container and nothing uploads it; the
    container's stdout is the only durable record. `detail` truncates at five (`_split_verdict`), so
    without this the sixth drift onward was unrecoverable in production -- and under the split that now
    happens on an exit-0 PASS run, where before it at least rode an exit-1 that paged. Printed for WARN
    and RED alike, on every path that produces a bundle. ASCII-only (cp1252 console)."""
    errs = stage.get("errors") or []
    if len(errs) <= 1:
        return          # the single error is already the whole of `detail`
    n = len(errs)
    for i, e in enumerate(errs, 1):
        print(f"    {label} {table} {stage['name']} error {i}/{n}: {e}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="silver_rebuild_gate (SILVER-C001): consumer-sync dispatcher")
    ap.add_argument("--tables", required=True, help="comma-separated table ids that were rebuilt")
    ap.add_argument("--asof", default="2026-02-15", help="census as-of (for the --diff baseline); full ISO timestamps are truncated to the date so scheduler context attributes work")
    ap.add_argument("--baseline-uri", default=None,
                    help="s3://bucket/key of the rolling baseline census.json to --diff against "
                         "(scheduled gate). Overrides CENSUS_BASELINE_S3. Unset -> the image-baked "
                         "data/cascade_census/as_of_date={asof}/census.json (backward compatible).")
    ap.add_argument("--json", dest="out", default=None, help="artifact bundle path (default: reports/...)")
    a = ap.parse_args(argv)
    a.asof = str(a.asof)[:10]  # scheduler passes <aws.scheduler.scheduled-time> (full ISO)
    tables = [t.strip() for t in a.tables.split(",") if t.strip()]
    if not tables:
        print("FAIL silver_rebuild_gate: no --tables given")
        return 1

    # -----------------------------------------------------------------------------------------
    # FENCE (incident I-1) -- IMAGE-AGE PREFLIGHT, at the EARLIEST possible moment.
    # This sits BEFORE baseline_uri resolution and BEFORE _build_live_context(), i.e. before the
    # S3 baseline GET (_load_census_from_s3) and before the psycopg connect. On 2026-07-24 the ask
    # (silver_futures_eod, terraform-applied and current) was newer than the container's baked
    # configs/silver/tables/ (43 files from commit e0a33bf2), and the only line the operator got
    # named the REGISTRY -- so the week was spent staring at a config file that was correct.
    # The banner prints on EVERY run, pass or fail: the cheap permanent record.
    # -----------------------------------------------------------------------------------------
    facts = image_stamp.image_facts()
    for line in image_stamp.banner("silver_rebuild_gate", facts):
        print(line)
    pre = _preflight_image_config(tables)
    if not pre["ok"]:
        for line in pre["lines"]:
            print(line)
        bundle = _preflight_bundle(tables, a.asof, pre)
        dest = Path(a.out) if a.out else _artifact_path(bundle["run_id"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(bundle, indent=1), encoding="utf-8")
        b = bundle["banner"]
        print(f"silver_rebuild_gate {bundle['run_id']} -> {dest}")
        print(f"  tables={b['tables']} branchA={b['branch_a']} branchB={b['branch_b']} "
              f"unknown={b['unknown']} red={b['red_tables']}  verdict={bundle['verdict']}")
        return 1

    # CLI --baseline-uri wins; CENSUS_BASELINE_S3 is the env fallback; empty/whitespace -> unset.
    baseline_uri = (a.baseline_uri or os.environ.get("CENSUS_BASELINE_S3") or "").strip() or None

    from leviathan.silver.registry import RegistryError  # already imported by the preflight above

    try:
        ctx = _build_live_context(tables, census_asof=a.asof, baseline_uri=baseline_uri)
    except BaselineFetchError as e:
        # Fail closed: a scheduled gate never runs against a stale/absent baseline (no image-baked fallback).
        print(f"FAIL silver_rebuild_gate: {e}")
        return 1
    except RegistryError as e:
        # FENCE (I-1), the OTHER half of the discrimination. A malformed yaml BAKED INTO THIS
        # IMAGE is a CONFIG fault, not an age fault -- and until now it left the job as a raw
        # traceback out of _build_live_context, which names no cause at all. The preflight's cheap
        # path deliberately does not parse the registry (2.2s), so this is where that class lands.
        pre_bad = {"ok": False, "reason": "baked_registry_unloadable",
                   "lines": image_stamp.explain_bad_registry(
                       "%s: %s" % (type(e).__name__, e), facts=facts),
                   "red_tables": [(t, "baked F010 registry in this image does not load: %s: %s"
                                   % (type(e).__name__, str(e)[:160])) for t in tables],
                   "image": facts}
        for line in pre_bad["lines"]:
            print(line)
        bundle = _preflight_bundle(tables, a.asof, pre_bad)
        dest = Path(a.out) if a.out else _artifact_path(bundle["run_id"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(bundle, indent=1), encoding="utf-8")
        print(f"silver_rebuild_gate {bundle['run_id']} -> {dest}")
        return 1
    bundle = run_gate(tables, ctx)

    # NOTE: `Path` comes from the MODULE-level import (line 53). The old function-local
    # `from pathlib import Path` here made `Path` a local name for the whole of main(), which
    # would UnboundLocalError the moment anything earlier in main() used it (the I-1 preflight
    # does). Removed deliberately -- behaviour is identical.
    dest = Path(a.out) if a.out else _artifact_path(bundle["run_id"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(bundle, indent=1), encoding="utf-8")

    b = bundle["banner"]
    print(f"silver_rebuild_gate {bundle['run_id']} -> {dest}")
    print(f"  tables={b['tables']} branchA={b['branch_a']} branchB={b['branch_b']} "
          f"unknown={b['unknown']} red={b['red_tables']} global_drift={b['global_drift']} "
          f" verdict={bundle['verdict']}")
    # D-PR-5: a WARN is exit 0, so the container log is the ONLY place it appears today. Print it above
    # the FAIL block, never inside it -- a promote that rode over another table's drift is a fact the
    # operator must be able to grep for. (The metric+alarm half is D-PR-28 and is NOT in this item.)
    # The summary line is followed by the UNTRUNCATED error list (`_print_stage_errors`): on the
    # scheduled path stdout is the only artifact that survives the container, and `detail` stops at five.
    for r in bundle["results"]:
        for s in r["stages"]:
            if s["status"] == WARN:
                print(f"  WARN {r['table']} (branch {r['branch']}): {s['name']}={s['detail']}")
                _print_stage_errors("WARN", r["table"], s)
    for r in bundle["results"]:
        if not r["ok"]:
            reds = [s for s in r["stages"] if s["status"] == "red"]
            print(f"  FAIL {r['table']} (branch {r['branch']}): "
                  + "; ".join(f"{s['name']}={s['detail']}" for s in reds))
            for s in reds:
                _print_stage_errors("FAIL", r["table"], s)
    return 0 if bundle["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
