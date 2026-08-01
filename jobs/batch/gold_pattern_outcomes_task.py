"""AWS Batch Fargate task: gold_pattern_records (firings) x silver_futures_eod -> gold_pattern_outcomes.

OUTCOMES_JOIN J5 -- the pattern-records variance axis (plan items 76-85, D-OJ-11/12).

WHAT THIS FILE IS, AND WHAT IT DELIBERATELY IS NOT
    The I/O + orchestration SHELL. It computes NOTHING. The join and the PIT clamp are
    ``leviathan.graphrag.numbers.outcomes`` over ``leviathan.silver.futures_roll``; the ledger-side
    rules (resolve-or-skip, the leakage fence, the key, the row invariants, the reconcile identity) are
    ``leviathan.graphrag.numbers.pattern_records``. That split is why the whole computation is testable
    on synthetic frames while only this file needs AWS -- the same shape gold_weather_z_task.py and
    gold_futures_outcomes_task.py use.

WHAT IT ADDS OVER THE FUTURES BUILDER, WHICH IS THE ONLY REASON IT EXISTS SEPARATELY
    The anchors are FIRINGS, not dated events, and firings come with three hazards the futures builder
    never sees:
      * ``contract`` holds BOTH graph node names and price-tape slugs -- the live ledger carries
        ``(corn, export_pace)`` AND ``(corn_cbot, export_pace)``. Only the slug shape maps to a series
        and ``coverage_start_for`` RAISES on the rest, so the path is RESOLVE OR SKIP, never guess, and
        the skipped count is PUBLISHED and RECONCILED (``resolved + skipped == ledger rows``). A table
        that quietly covers half the ledger while looking complete is the failure this reconcile is for.
      * cascade x backfill_grid verdicts were replayed against a SYNTHESIZED as-of axis. They stay on
        S3 as an audit record and they are never joined to price: a move joined to a leaked verdict is
        a leaked row however clean the price side is.
      * the verdict's own INGEST axis (``written_at``) has to travel onto the outcome row, because a
        backfill verdict for a 2023 asof was written in 2026 and a row guarded only on the firing date
        would be readable at an asof at which the verdict did not exist.

THE FULL REBUILD IS THE DESIGN (item 82 / D-OJ-15)
    Every run rebuilds every requested partition from the ledger and the tape. No watermark, no append,
    no incremental state -- which is what makes the table RE-DERIVABLE, and re-derivability is what its
    PIT claim actually rests on. ``built_at`` is PROVENANCE and deliberately NOT a guard axis: under a
    full rebuild every row carries the same stamp, so ``built_at <= asof`` is all-pass or all-fail and
    cannot bind. The acceptance leg that replaces it is ``--rebuild-diff``.

THE ASOF IS AN ARGUMENT, NEVER THE WALL CLOCK
    A job that read "now" from the clock would move the PIT boundary between two runs of the same
    build, and a rebuild-diff over a moving boundary proves nothing.

NOTHING HERE SCHEDULES ANYTHING. Per the ratified gate table J5's recurring refresh waits on the
20-day parity soak, and per the standing directive a new schedule submits to queue-ondemand (never the
SPOT queue) with its exact command smoke-tested before its first fire. This file is run by hand.

Usage (compute is offline-testable; publishing is the gated step):
    python jobs/batch/gold_pattern_outcomes_task.py --asof 2026-07-31 --ledger-dir ./ledger \\
        --tape-dir ./tape --out-dir ./out --publish-mode dry-run --rebuild-diff
    python jobs/batch/gold_pattern_outcomes_task.py --asof 2026-07-31 --provenance daily_sweep \\
        --bucket leviathan-dev-shahem-001 --publish-mode dry-run
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:                     # jobs/ is not an importable package
    sys.path.insert(0, str(_REPO / "src"))

from leviathan.graphrag.numbers import outcomes as OC  # noqa: E402
from leviathan.graphrag.numbers import pattern_records as PR  # noqa: E402
from leviathan.silver import futures_eod_contracts as FC  # noqa: E402

TABLE = "gold_pattern_outcomes"
DATABASE = "leviathan_dev"
S3_PREFIX = "gold/pattern_outcomes"
LEDGER_PREFIX = "gold/pattern_records"
TAPE_PREFIX = "silver/futures_eod"
CONTRACT_PATH = _REPO / "configs" / "silver" / "tables" / f"{TABLE}.yaml"

# The ledger columns the join reads. The VALUE columns (streak_len, window_change, n_points...) are
# deliberately NOT among them: the join must not be able to see the measurement the verdict was made
# from, or a later reader could not tell an outcome from a re-statement of the verdict.
LEDGER_COLUMNS = ["record_kind", "contract", "driver_or_chain_id", "provenance", "as_of_date",
                  "verdict", "decline_reason", "written_at"]
TAPE_COLUMNS = ["leviathan_slug", "trade_date", "contract_month", "settle",
                "unit", "currency", "settle_kind", "open_interest", "volume", "instrument_kind"]

# Path COMPONENTS under the ledger prefix that are not canonical rows. Counting the shadow copies
# double-reports every figure -- the pattern-records census had to say so explicitly, and so does this
# reader. Matched as whole components rather than as substrings: a substring test excludes any path
# that merely CONTAINS the word (a temp directory named `.../test_the_shadow.../`), which silently
# reads zero rows and looks exactly like an empty ledger.
NON_CANONICAL_PARTS = frozenset({"_shadow", "_manifests"})

logger = logging.getLogger("gold_pattern_outcomes")


def _load_contract() -> dict:
    """The SILVER-F010 contract -- the schema/partition-order authority a publish writes through.

    NOT PRESENT WHEN THIS JOB WAS WRITTEN, and the error says so rather than failing deep in a staging
    loop. Registering the table is one atomic change (contract -> generated DDL -> dag_catalog family +
    freshness target + alarm -> the numbers card), and the recipe lives in the staged card's header at
    configs/graphrag/numbers/cards/gold_pattern_outcomes.yaml. Every compute path (--publish-mode
    dry-run, --out-dir, --rebuild-diff) runs WITHOUT it."""
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(
            f"{CONTRACT_PATH} does not exist -- {TABLE} has no SILVER-F010 contract yet, so there is "
            f"no schema authority to publish through. Generate it from "
            f"leviathan.graphrag.numbers.pattern_records.po_column_types() / PO_PARTITION_TYPES, then "
            f"`python scripts/silver/generate_ddls_from_registry.py --write` (never hand-write the "
            f"DDL). Until then use --publish-mode dry-run --out-dir <dir>."
        )
    import yaml
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8")) or {}


# ---------------------------------------------------------------------------------------------------
# Reads. Both lanes are S3-DIRECT (list + get), never Athena and never the Glue catalog: a partition-
# projection enumeration is the Jul-2026 LIST-storm class and this job has no reason to open it.
# ---------------------------------------------------------------------------------------------------
def is_canonical(path: str, *, root: Optional[str] = None) -> bool:
    """False for a `_shadow/` or `_manifests/` copy. Component-wise, never a substring test."""
    rel = str(path).replace("\\", "/")
    if root:
        rel = rel[len(str(root).replace("\\", "/")):]
    return not (NON_CANONICAL_PARTS & set(rel.split("/")))


def read_ledger_local(ledger_dir: str) -> pd.DataFrame:
    frames = [pd.read_parquet(p) for p in sorted(Path(ledger_dir).rglob("*.parquet"))
              if is_canonical(p.as_posix(), root=Path(ledger_dir).as_posix())]
    if not frames:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    return _narrow(pd.concat(frames, ignore_index=True), LEDGER_COLUMNS)


def read_ledger_s3(bucket: str, *, region: str = "us-east-1", asof: Optional[str] = None) -> pd.DataFrame:
    """The canonical ledger, read directly from its registered as_of_date partitions.

    Partitions whose as_of_date POSTDATES the build asof are not read at all: a firing the reader
    cannot know about cannot anchor an outcome, and dropping them at the read is cheaper and harder to
    get wrong than filtering them later."""
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )
    client = get_thread_local_s3_client(region)
    frames = []
    for key in list_s3_keys(bucket, f"{LEDGER_PREFIX}/", suffix=".parquet", aws_region=region):
        if not is_canonical(key):
            continue
        part = _hive_value(key, "as_of_date")
        if asof and part and part > str(asof)[:10]:
            continue
        frame = pd.read_parquet(io.BytesIO(s3_download_with_retry(bucket, key, client)))
        if "as_of_date" not in frame.columns and part:
            frame["as_of_date"] = part                    # hive partition col, not in the payload
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    return _narrow(pd.concat(frames, ignore_index=True), LEDGER_COLUMNS)


def read_tape_local(tape_dir: str, slugs: Optional[list] = None) -> pd.DataFrame:
    frames = [pd.read_parquet(p) for p in sorted(Path(tape_dir).rglob("*.parquet"))]
    if not frames:
        return pd.DataFrame(columns=TAPE_COLUMNS)
    tape = _narrow(pd.concat(frames, ignore_index=True), TAPE_COLUMNS)
    return tape[tape["leviathan_slug"].astype("string").isin(list(slugs))].copy() if slugs else tape


def read_tape_s3(bucket: str, slugs: list, *, region: str = "us-east-1") -> pd.DataFrame:
    """The tape, pruned by slug prefix -- only the slugs the resolved firings actually need."""
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )
    client = get_thread_local_s3_client(region)
    frames = []
    for slug in sorted(set(slugs)):
        for key in list_s3_keys(bucket, f"{TAPE_PREFIX}/leviathan_slug={slug}/",
                                suffix=".parquet", aws_region=region):
            frame = pd.read_parquet(io.BytesIO(s3_download_with_retry(bucket, key, client)))
            if "leviathan_slug" not in frame.columns:
                frame["leviathan_slug"] = slug
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=TAPE_COLUMNS)
    return _narrow(pd.concat(frames, ignore_index=True), TAPE_COLUMNS)


def _hive_value(key: str, field: str) -> Optional[str]:
    for part in str(key).split("/"):
        if part.startswith(f"{field}="):
            return part.split("=", 1)[1]
    return None


def _narrow(frame: pd.DataFrame, columns: list) -> pd.DataFrame:
    for col in columns:
        if col not in frame.columns:
            frame[col] = pd.NA
    return frame[columns].copy()


# ---------------------------------------------------------------------------------------------------
# The build. Every rule is imported; this function is plumbing and an assertion.
# ---------------------------------------------------------------------------------------------------
def build(ledger: pd.DataFrame, tape: pd.DataFrame, *, asof: str, built_at: str,
          horizons: tuple, kinds: Optional[list] = None,
          provenance: Optional[str] = None) -> tuple[pd.DataFrame, dict]:
    """One full rebuild: firings -> anchors -> the J1 join -> the ledger key re-attached.

    The reconcile identity is asserted HERE rather than logged, because a silently-half-covered outcome
    table looks exactly like a correct one from the outside (item 81 / acceptance (i))."""
    rows = ledger.to_dict("records") if len(ledger) else []
    resolved = PR.po_ledger_anchors(rows, kinds=kinds, provenance=provenance)
    if len(resolved["anchors"]) + resolved["skipped"] != len(rows):
        raise ValueError(
            f"anchor reconcile FAILED: {len(resolved['anchors'])} resolved + {resolved['skipped']} "
            f"skipped != {len(rows)} ledger rows -- a firing that is neither joined nor counted as "
            f"skipped is a silent coverage hole")
    frame = OC.build_outcomes(resolved["anchors"], tape, asof=asof, built_at=built_at,
                              horizons=horizons)
    frame = attach_ledger_key(frame, resolved["meta"])
    problems = PR.lint_pattern_outcome_rows(frame.to_dict("records"))
    if problems:
        raise ValueError(f"{len(problems)} pattern-outcome invariant violation(s); first 5: "
                         + "; ".join(problems[:5]))
    return frame, resolved


def attach_ledger_key(frame: pd.DataFrame, meta: dict) -> pd.DataFrame:
    """Re-attach the ledger key + its ingest stamp to each built outcome row, and rename the join's
    `event_year` partition to `as_of_year`.

    The number is identical (a pattern outcome's anchor IS the firing date, and the row lint pins that
    equality) -- the NAME differs because this table's axis is the ledger's as_of_date, and a partition
    called `event_year` on a table whose reader-facing period is `as_of_date` is the kind of small
    mismatch that later gets 'fixed' in the wrong direction."""
    cols = list(PR.po_columns())
    if not len(frame):
        return pd.DataFrame(columns=cols + ["as_of_year"])
    out = frame.copy()
    for col in PR.PO_KEY_COLUMNS + PR.PO_EXTRA_COLUMNS:
        out[col] = out["event_key"].map(lambda k, c=col: (meta.get(str(k)) or {}).get(c))
    if "event_year" in out.columns:
        out = out.rename(columns={"event_year": "as_of_year"})
    else:
        out["as_of_year"] = out["as_of_date"].astype("string").str.slice(0, 4).astype(int)
    out = out.sort_values(["leviathan_slug", "as_of_date", "event_key", "horizon_days"],
                          kind="mergesort").reset_index(drop=True)
    return out[cols + ["as_of_year"]]


def summarize(frame: pd.DataFrame, resolved: dict) -> dict:
    """The build's own honest census. `pending` is published beside `closed` -- always, everywhere -- and
    the skip census rides beside both, because the two ways this table can be incomplete (a horizon
    that has not closed, a contract that does not resolve) are different facts and a reader who is
    shown only one of them cannot tell which happened."""
    census = PR.po_reconcile(frame.to_dict("records") if len(frame) else [])
    return {"rows": int(len(frame)), "pairs": census["pairs"],
            "closed": census["n_closed"], "pending": census["n_pending"],
            "declined": census["n_declined"],
            "declined_by_reason": ({str(k): int(v) for k, v in
                                    frame.loc[frame["status"].astype("string")
                                              .str.startswith(OC.STATUS_DECLINED_PREFIX),
                                              "decline_reason"].value_counts().items()}
                                   if len(frame) else {}),
            "anchors_resolved": len(resolved.get("anchors") or []),
            "anchors_skipped": resolved.get("skipped", 0),
            "skipped_by_reason": resolved.get("skipped_by_reason") or {},
            "ledger_pairs": resolved.get("pairs", 0),
            "ledger_pairs_resolved": resolved.get("resolved_pairs", 0),
            "slugs": int(frame["leviathan_slug"].nunique()) if len(frame) else 0,
            "fingerprint": OC.outcomes_fingerprint(frame)}


def write_local(frame: pd.DataFrame, out_dir: str) -> list:
    """The registered-partition layout, written locally for inspection and for the rebuild-and-diff
    acceptance leg without touching S3."""
    written = []
    if not len(frame):
        return written
    for (slug, year), part in frame.groupby(["leviathan_slug", "as_of_year"], sort=True):
        d = Path(out_dir) / f"leviathan_slug={slug}" / f"as_of_year={int(year)}"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "pattern_outcomes.parquet"
        part.drop(columns=["leviathan_slug", "as_of_year"]).to_parquet(path, index=False)
        written.append(str(path))
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", required=True,
                    help="the PIT as-of (YYYY-MM-DD). REQUIRED: the boundary is never the wall clock")
    ap.add_argument("--ledger-dir", default="", help="read gold_pattern_records from a local tree")
    ap.add_argument("--tape-dir", default="", help="read silver_futures_eod from a local tree")
    ap.add_argument("--kinds", default=",".join(sorted(PR.V1_KINDS)))
    ap.add_argument("--provenance", default="", choices=("", PR.PROV_DAILY_SWEEP, PR.PROV_BACKFILL_GRID),
                    help="pin ONE provenance class (default: both, never mixed within a key)")
    ap.add_argument("--horizons", default=",".join(str(h) for h in PR.PO_HORIZONS))
    ap.add_argument("--out-dir", default="", help="also write the partitions locally")
    ap.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET", ""))
    ap.add_argument("--publish-mode", default="dry-run", choices=("dry-run", "shadow", "write"))
    ap.add_argument("--shadow-prefix", default=None)
    ap.add_argument("--rebuild-diff", action="store_true",
                    help="D-OJ-15: build TWICE and assert an identical content fingerprint")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    horizons = tuple(int(h) for h in str(args.horizons).split(",") if str(h).strip())
    unsupported = [h for h in horizons if h not in PR.PO_HORIZONS]
    if unsupported:
        # AM-1: a year horizon does not exist under this basis. Refused loudly, never rounded to 90.
        logger.error("unsupported horizon(s) %s: %s", unsupported,
                     PR.po_horizon_decline(unsupported[0])["detail"])
        return 2
    kinds = [k.strip() for k in str(args.kinds).split(",") if k.strip()]
    bad_kinds = [k for k in kinds if k not in PR.V1_KINDS]
    if bad_kinds:
        logger.error("unknown record kind(s) %s -- v1 kinds are %s", bad_kinds, sorted(PR.V1_KINDS))
        return 2

    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    if args.ledger_dir:
        ledger = read_ledger_local(args.ledger_dir)
    else:
        if not args.bucket:
            logger.error("--bucket (or LEVIATHAN_BUCKET) is required unless --ledger-dir is given")
            return 2
        ledger = read_ledger_s3(args.bucket, region=region, asof=args.asof)
    if not len(ledger):
        logger.error("the ledger read returned ZERO rows -- refusing to build an outcome table out of "
                     "nothing (a silent empty build is the T2b stale-mirror shape)")
        return 3

    # The slugs the RESOLVED firings need -- a dry resolve first, so the tape read pulls exactly the
    # series the join will use and nothing else.
    probe = PR.po_ledger_anchors(ledger.to_dict("records"), kinds=kinds,
                                 provenance=args.provenance or None)
    slugs = sorted({a["leviathan_slug"] for a in probe["anchors"]})
    logger.info("ledger: %d rows, %d pairs -> %d anchors on %d slug(s); skipped %d %s",
                len(ledger), probe["pairs"], len(probe["anchors"]), len(slugs), probe["skipped"],
                json.dumps(probe["skipped_by_reason"]))
    if not slugs:
        logger.error("no firing resolved to a price-tape slug (skips: %s) -- there is nothing to join. "
                     "The ledger's `contract` holds graph node names as well as slugs, and a node name "
                     "is SKIPPED rather than guessed at.", json.dumps(probe["skipped_by_reason"]))
        return 3
    unmapped = [s for s in slugs if s not in FC.CONTRACT_MAP]
    if unmapped:                                      # unreachable via po_resolve_slug; belt and braces
        logger.error("unmapped slug(s) %s -- coverage is never inferred", unmapped)
        return 2

    tape = read_tape_local(args.tape_dir, slugs) if args.tape_dir else read_tape_s3(
        args.bucket, slugs, region=region)
    if not len(tape):
        logger.error("the tape read returned ZERO rows for %s -- refusing to build", slugs)
        return 3
    edges = OC.tape_edges(tape)
    for slug in slugs:
        logger.info("tape edge %s = %s", slug, edges.get(slug))
        if slug not in edges:
            # The per-slug edge is half the clamp and it has no card-spec representation; a slug with
            # no edge would fall back to `asof - lag` and clamp four sessions too late on Databento.
            logger.error("no tape edge for %s -- the PER-SLUG clamp cannot be established, and a "
                         "global edge would push this slug's boundary onto sessions it has no data "
                         "for. Refusing.", slug)
            return 3

    built_at = pd.Timestamp.utcnow().tz_localize(None).isoformat(timespec="seconds")
    frame, resolved = build(ledger, tape, asof=args.asof, built_at=built_at, horizons=horizons,
                            kinds=kinds, provenance=args.provenance or None)
    census = summarize(frame, resolved)
    logger.info("build census: %s", json.dumps(census, default=str))

    if args.rebuild_diff:
        again, _ = build(ledger, tape, asof=args.asof, built_at="1970-01-01T00:00:00",
                         horizons=horizons, kinds=kinds, provenance=args.provenance or None)
        if OC.outcomes_fingerprint(frame) != OC.outcomes_fingerprint(again):
            logger.error("REBUILD-DIFF FAILED: two builds at the same tape edge differ. This table's "
                         "whole PIT claim is a reproducibility claim (D-OJ-15); a non-deterministic "
                         "build voids it.")
            return 4
        logger.info("rebuild-diff OK: %s", census["fingerprint"])

    if args.out_dir:
        written = write_local(frame, args.out_dir)
        logger.info("wrote %d local partition file(s) under %s", len(written), args.out_dir)

    if args.publish_mode == "dry-run":
        logger.info("--publish-mode dry-run: nothing written to S3")
        return 0

    import boto3
    from leviathan.common.publish_guard import PublishTarget, authorize_publish
    from leviathan.silver.partitioned_producer import build_partitioned_publish
    from leviathan.silver.publisher import ManifestState
    contract = _load_contract()
    bucket = args.bucket or contract.get("s3_bucket")
    ident = boto3.client("sts", region_name=region).get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database=DATABASE,
                      prefix=f"{S3_PREFIX}/", role_arn=ident["Arn"], table=TABLE),
        argv=["--publish-mode", args.publish_mode])
    plan = build_partitioned_publish(
        df=frame, contract=contract, auth=auth, job="gold_pattern_outcomes",
        s3_client=boto3.client("s3", region_name=region),
        glue_client=boto3.client("glue", region_name=region) if auth.may_mutate_canonical else None,
        code_sha=os.environ.get("IMAGE_TAG", ""), shadow_prefix=args.shadow_prefix,
        # The clamp and the ledger key as WRITE-TIME invariants: a move readable before its horizon
        # closed, a pending row carrying a price, a row built from a fenced verdict, or a row whose key
        # does not trace back to a ledger firing never reaches S3.
        row_validator=lambda df: PR.lint_pattern_outcome_rows(df.to_dict("records")))
    logger.info("publish complete: mode=%s state=%s", auth.mode.value, plan.manifest.state.value)
    return 1 if plan.manifest.state == ManifestState.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
