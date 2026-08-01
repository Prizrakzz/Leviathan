"""AWS Batch Fargate task: silver_futures_eod + dated events -> gold_futures_outcomes (OUTCOMES_JOIN J1).

WHAT THIS FILE IS, AND WHAT IT DELIBERATELY IS NOT
    This is the I/O + orchestration SHELL. Every rule lives elsewhere and is imported:
    ``leviathan.graphrag.numbers.outcomes`` (the join core + the PIT clamp) over
    ``leviathan.silver.futures_roll`` (the survivor selection). This file computes NOTHING -- the same
    split ``gold_weather_z_task.py`` uses, and the reason the compute is unit-testable on synthetic
    frames while the shell needs AWS.

THE FULL REBUILD IS THE DESIGN (plan item 82 / D-OJ-15)
    Each run rebuilds every requested partition from the tape and the event source; there is no
    incremental state, no watermark, and no append. That is what makes the table RE-DERIVABLE, which is
    the property this table's PIT claim actually rests on -- ``built_at`` is PROVENANCE and is
    deliberately NOT a guard axis (under a full rebuild every row carries the same stamp, so
    ``built_at <= asof`` is all-pass or all-fail and cannot bind). The acceptance leg is instead
    ``--rebuild-diff``: two consecutive builds at the same tape edge must produce the same content
    fingerprint, with ``built_at`` excluded because it is not data.

THE ASOF IS AN ARGUMENT, NEVER THE WALL CLOCK
    The PIT boundary is ``min(asof - tape_lag, per-slug max(trade_date))``. A job that read "now" from
    the clock would make a rebuild non-reproducible AND would silently move the boundary between two
    runs of the same build. ``--asof`` is required.

THE PER-SLUG TAPE EDGE IS ENFORCED HERE
    No ``TableSpec`` field can express "per-slug max(trade_date)", so the builder is where that half of
    the clamp lives (plan item 46a). The 15 Databento slugs run four sessions behind the 7 free legs; a
    row whose horizon closes past its OWN slug's edge is written ``pending``, never ``closed``. The
    edges are MEASURED from the tape that was actually read -- never assumed, never global.

Usage (compute is offline-testable; publishing is the gated step):
    python jobs/batch/gold_futures_outcomes_task.py --asof 2026-07-31 --anchors anchors.json \\
        --tape-dir ./tape --out-dir ./out --publish-mode dry-run
    python jobs/batch/gold_futures_outcomes_task.py --asof 2026-07-31 --anchors s3://.../anchors.json \\
        --slugs corn_cbot,soybean_oil_cbot --publish-mode write
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
from leviathan.silver import futures_eod_contracts as FC  # noqa: E402

TABLE = "gold_futures_outcomes"
DATABASE = "leviathan_dev"
S3_PREFIX = "gold/futures_outcomes"
TAPE_PREFIX = "silver/futures_eod"
CONTRACT_PATH = _REPO / "configs" / "silver" / "tables" / f"{TABLE}.yaml"

# The tape columns the join reads. Narrower than the table: an outcome needs the key, the price and the
# three labels that make the price attributable. Pulling the whole row would drag OHLC/volume columns
# that are NULL by construction on every settle-only source.
TAPE_COLUMNS = ["leviathan_slug", "trade_date", "contract_month", "settle",
                "unit", "currency", "settle_kind", "open_interest", "volume", "instrument_kind"]

logger = logging.getLogger("gold_futures_outcomes")


def _load_contract() -> dict:
    """The SILVER-F010 contract -- the schema / partition-order authority the publisher writes through.

    NOT YET PRESENT AT THE TIME THIS JOB WAS WRITTEN, and the error says so rather than letting a
    publish fail deep in the staging loop. Registering the table is one atomic change (contract ->
    generated DDL -> dag_catalog family + freshness target + alarm -> the numbers card), and the recipe
    lives in the staged card's header, configs/graphrag/numbers/cards/gold_futures_outcomes.yaml. Every
    compute path (--publish-mode dry-run, --out-dir, --rebuild-diff) runs WITHOUT it."""
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(
            f"{CONTRACT_PATH} does not exist -- {TABLE} has no SILVER-F010 contract yet, so there is "
            f"no schema authority to publish through. Generate it from "
            f"leviathan.graphrag.numbers.outcomes.OUTCOME_COLUMN_TYPES / OUTCOME_PARTITION_TYPES, then "
            f"`python scripts/silver/generate_ddls_from_registry.py --write` (never hand-write the "
            f"DDL). Until then use --publish-mode dry-run --out-dir <dir>."
        )
    import yaml
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8")) or {}


def load_anchors(path: str) -> list[dict]:
    """The EVENT side of the join: ``[{leviathan_slug, event_key, event_date}, ...]``.

    JSON (a list, or ``{"anchors": [...]}``) or CSV. FAIL CLOSED on a missing field: an anchor with no
    event date is not an anchor, and defaulting one would invent a window."""
    text = Path(path).read_text(encoding="utf-8")
    if path.endswith(".csv"):
        rows = pd.read_csv(io.StringIO(text)).to_dict("records")
    else:
        doc = json.loads(text)
        rows = doc.get("anchors") if isinstance(doc, dict) else doc
    out: list[dict] = []
    for i, r in enumerate(rows or []):
        missing = [k for k in ("leviathan_slug", "event_key", "event_date") if not r.get(k)]
        if missing:
            raise ValueError(f"anchor {i} is missing {missing} -- an anchor with no event date cannot "
                             f"be joined; fix the source rather than defaulting it")
        out.append({"leviathan_slug": str(r["leviathan_slug"]), "event_key": str(r["event_key"]),
                    "event_date": str(r["event_date"])[:10]})
    return out


def read_tape_local(tape_dir: str, slugs: Optional[list[str]] = None) -> pd.DataFrame:
    """Read the tape from a local parquet tree (offline runs, fixtures, and the CEPEA control leg)."""
    frames = []
    for p in sorted(Path(tape_dir).rglob("*.parquet")):
        frame = pd.read_parquet(p)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=TAPE_COLUMNS)
    tape = pd.concat(frames, ignore_index=True)
    return _narrow(tape, slugs)


def read_tape_s3(bucket: str, slugs: list[str], *, region: str = "us-east-1") -> pd.DataFrame:
    """Read the per-delivery-month tape DIRECTLY from S3, pruned by slug prefix (the load_pg_numbers
    no-Athena pattern: the Glue catalog is never touched here, so a partition-projection enumeration
    surface is never opened -- the Jul-2026 LIST-storm class stays out)."""
    from leviathan.storage.s3 import (
        get_thread_local_s3_client,
        list_s3_keys,
        s3_download_with_retry,
    )
    client = get_thread_local_s3_client(region)
    frames = []
    for slug in slugs:
        prefix = f"{TAPE_PREFIX}/leviathan_slug={slug}/"
        for key in list_s3_keys(bucket, prefix, suffix=".parquet", aws_region=region):
            body = s3_download_with_retry(bucket, key, client)
            frame = pd.read_parquet(io.BytesIO(body))
            if "leviathan_slug" not in frame.columns:      # hive partition col, not in the payload
                frame["leviathan_slug"] = slug
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=TAPE_COLUMNS)
    return _narrow(pd.concat(frames, ignore_index=True), slugs)


def _narrow(tape: pd.DataFrame, slugs: Optional[list[str]]) -> pd.DataFrame:
    for col in TAPE_COLUMNS:
        if col not in tape.columns:
            tape[col] = pd.NA
    if slugs:
        tape = tape[tape["leviathan_slug"].astype("string").isin(list(slugs))]
    return tape[TAPE_COLUMNS].copy()


def build(anchors: list[dict], tape: pd.DataFrame, *, asof: str, built_at: str,
          horizons: tuple[int, ...]) -> pd.DataFrame:
    """One full rebuild. Everything interesting happens inside ``outcomes.build_outcomes``."""
    frame = OC.build_outcomes(anchors, tape, asof=asof, built_at=built_at, horizons=horizons)
    problems = OC.lint_outcome_row_invariants(frame.to_dict("records"))
    if problems:
        raise ValueError(f"{len(problems)} outcome-row invariant violation(s); first 5: "
                         + "; ".join(problems[:5]))
    return frame


def summarize(frame: pd.DataFrame) -> dict:
    """The build's own honest census -- closed / pending / declined-by-reason. `n_pending` is published
    beside `n_closed` for the same reason every aggregate publishes it: a pending firing that vanishes
    biases every downstream base rate toward OLD firings."""
    if frame.empty:
        return {"rows": 0, "closed": 0, "pending": 0, "declined": {}}
    status = frame["status"].astype("string")
    declined = (frame.loc[status.str.startswith(OC.STATUS_DECLINED_PREFIX), "decline_reason"]
                .value_counts().to_dict())
    return {"rows": int(len(frame)),
            "closed": int((status == OC.STATUS_CLOSED).sum()),
            "pending": int((status == OC.STATUS_PENDING).sum()),
            "declined": {str(k): int(v) for k, v in sorted(declined.items())},
            "slugs": int(frame["leviathan_slug"].nunique()),
            "fingerprint": OC.outcomes_fingerprint(frame)}


def write_local(frame: pd.DataFrame, out_dir: str) -> list[str]:
    """Write the registered-partition layout locally (hive dirs), for inspection and for the
    rebuild-and-diff acceptance leg without touching S3."""
    written: list[str] = []
    if frame.empty:
        return written
    for (slug, year), part in frame.groupby(["leviathan_slug", "event_year"], sort=True):
        d = Path(out_dir) / f"leviathan_slug={slug}" / f"event_year={int(year)}"
        d.mkdir(parents=True, exist_ok=True)
        path = d / "futures_outcomes.parquet"
        part.drop(columns=["leviathan_slug", "event_year"]).to_parquet(path, index=False)
        written.append(str(path))
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", required=True,
                    help="the PIT as-of (YYYY-MM-DD). REQUIRED: the boundary is never the wall clock")
    ap.add_argument("--anchors", required=True, help="path to the event anchors (json or csv)")
    ap.add_argument("--slugs", default="", help="comma-separated slug filter (default: the anchors')")
    ap.add_argument("--horizons", default=",".join(str(h) for h in OC.HORIZON_DAYS))
    ap.add_argument("--tape-dir", default="", help="read the tape from a local parquet tree instead of S3")
    ap.add_argument("--out-dir", default="", help="also write the partitions locally")
    ap.add_argument("--bucket", default=os.environ.get("LEVIATHAN_BUCKET", ""))
    ap.add_argument("--publish-mode", default="dry-run", choices=("dry-run", "shadow", "write"))
    ap.add_argument("--shadow-prefix", default=None)
    ap.add_argument("--rebuild-diff", action="store_true",
                    help="D-OJ-15: build TWICE and assert an identical content fingerprint")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    horizons = tuple(int(h) for h in str(args.horizons).split(",") if str(h).strip())
    unsupported = [h for h in horizons if not OC.horizon_supported(h)]
    if unsupported:
        # AM-1: a YEAR horizon is EXCLUDED under this basis and is refused loudly rather than rounded.
        logger.error("unsupported horizon(s) %s: %s", unsupported,
                     OC.horizon_decline(unsupported[0])["detail"])
        return 2

    anchors = load_anchors(args.anchors)
    slugs = ([s.strip() for s in args.slugs.split(",") if s.strip()]
             or sorted({a["leviathan_slug"] for a in anchors}))
    unmapped = [s for s in slugs if s not in FC.CONTRACT_MAP]
    if unmapped:
        logger.error("unmapped slug(s) %s -- coverage is never inferred; add the curated "
                     "CONTRACT_MAP/PRICE_COVERAGE_START record first", unmapped)
        return 2

    if args.tape_dir:
        tape = read_tape_local(args.tape_dir, slugs)
    else:
        if not args.bucket:
            logger.error("--bucket (or LEVIATHAN_BUCKET) is required unless --tape-dir is given")
            return 2
        tape = read_tape_s3(args.bucket, slugs, region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    if tape.empty:
        logger.error("the tape read returned ZERO rows for %s -- refusing to build an outcome table "
                     "out of nothing (a silent empty build is the T2b stale-mirror shape)", slugs)
        return 3

    edges = OC.tape_edges(tape)
    for slug in sorted(slugs):
        logger.info("tape edge %s = %s", slug, edges.get(slug))
    built_at = pd.Timestamp.utcnow().tz_localize(None).isoformat(timespec="seconds")

    frame = build(anchors, tape, asof=args.asof, built_at=built_at, horizons=horizons)
    census = summarize(frame)
    logger.info("build census: %s", json.dumps(census, default=str))

    if args.rebuild_diff:
        again = build(anchors, tape, asof=args.asof, built_at="1970-01-01T00:00:00", horizons=horizons)
        if OC.outcomes_fingerprint(frame) != OC.outcomes_fingerprint(again):
            logger.error("REBUILD-DIFF FAILED: two builds at the same tape edge differ. The table's "
                         "whole PIT claim is a reproducibility claim (D-OJ-15); a non-deterministic "
                         "build voids it.")
            return 4
        logger.info("rebuild-diff OK: %s", OC.outcomes_fingerprint(frame))

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
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    ident = boto3.client("sts", region_name=region).get_caller_identity()
    auth = authorize_publish(
        PublishTarget(account_id=ident["Account"], bucket=bucket, database=DATABASE,
                      prefix=f"{S3_PREFIX}/", role_arn=ident["Arn"], table=TABLE),
        argv=["--publish-mode", args.publish_mode])
    plan = build_partitioned_publish(
        df=frame, contract=contract, auth=auth, job="gold_futures_outcomes",
        s3_client=boto3.client("s3", region_name=region),
        glue_client=boto3.client("glue", region_name=region) if auth.may_mutate_canonical else None,
        code_sha=os.environ.get("IMAGE_TAG", ""), shadow_prefix=args.shadow_prefix,
        # The clamp as a WRITE-TIME invariant: a move that would be readable before its horizon closed,
        # a pending row carrying a price, or a survivor-basis row that does not name its contract never
        # reaches S3. The F010 contract can only express unconditional nullability; this is the rest.
        row_validator=lambda df: OC.lint_outcome_row_invariants(df.to_dict("records")))
    logger.info("publish complete: mode=%s state=%s", auth.mode.value, plan.manifest.state.value)
    return 1 if plan.manifest.state == ManifestState.FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
