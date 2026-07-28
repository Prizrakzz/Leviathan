"""advance_rolling_census (A-W3 step 2) -- the SFN [Reconcile] task.

After a GREEN gate + a GREEN promote, the pipeline must roll the family's baseline FORWARD: it re-runs the
cascade census against the freshly-promoted canonical mirror and writes that post-census to the family's
rolling S3 baseline

    s3://leviathan-dev-shahem-001/cascade_census/rolling/{family}/census.json

so the NEXT scheduled gate diffs against THIS run's state, not a stale snapshot (the gate reads the same
rolling key via --baseline-uri and fails closed on a new un-waived DARK leg). Without this step the rolling
baseline never advances and every subsequent gate re-diffs against an ever-older census.

SAME IN-VPC MACHINERY AS THE GATE. The census only runs against the pg mirror (RDS is in-VPC only), so this
task runs on the SAME evidence-build jobdef/image the silver_rebuild_gate uses (src/+configs/ baked,
EVIDENCE_PG_DSN injected, Athena on the task role) and invokes the exact production census entry point
``leviathan.graphrag.numbers.cascade_census.main(["--asof", asof, "--json", tmp])``. That entry point runs
PG-ONLY under an Athena firewall + env asserts (GRAPHRAG_NUMBERS_BACKEND=pg + EVIDENCE_PG_DSN) and returns 0
IFF the census is clean (zero un-waived DARK legs). We roll a census forward ONLY on that clean rc==0 result.

FAIL CLOSED (a failed reconcile must FAIL the execution VISIBLY, never silently leave a stale baseline):
  * census raised (env assert / pg outage / Athena tripwire) -> nonzero exit, NO upload;
  * census returned nonzero (un-waived DARK leg) -> nonzero exit, NO upload (do NOT enshrine a dirty census
    as the new baseline);
  * the census artifact is missing after a claimed-clean run -> nonzero exit, NO upload;
  * the S3 upload failed -> nonzero exit.
Only a clean census (rc==0) whose artifact uploaded successfully returns 0. A nonzero exit from this Batch
task raises States.TaskFailed on the .sync integration -> the machine's Reconcile Catch -> [FailNotify].

READ-ONLY of Athena (never touches it); the ONLY S3 write is the rolling-baseline put_object. ASCII-only
stdout (the container console is cp1252-narrow; keep prints ASCII).

RECORDED DEFERRAL -- PRICE_AND_PLAYBOOKS W1.0 / D6 (silver_futures_eod), deferred to W1a.
----------------------------------------------------------------------------------------
The plan lists D6 as "gate baseline seed s3://.../cascade_census/rolling/futures_eod/census.json",
sited here. It is NOT seeded at W1.0, deliberately, and the deferral is written HERE rather than left
implied by silence (the same discipline as the D7 pg-mirror deferral recorded in place at
jobs/utils/load_pg_numbers.py). Grounds:

  * The task needs NO code change for it -- ``main()`` already takes ``--asof`` and ``--dest-uri``, so
    D6 is purely a runtime S3 write; nothing about it is blocked by W1.0 code.
  * A baseline is a CENSUS of legs that exist. At W1.0 ``silver_futures_eod`` has zero objects, zero
    registered partitions, ``cascade_ref: null`` and is whitelist-absent from the served numbers
    registry -- it feeds no cascade leg, so its census is empty BY CONSTRUCTION. Seeding an empty
    census would enshrine "no legs" as the baseline the first real gate diffs against, which is the
    stale-snapshot failure this task exists to prevent, pointed the other way.
  * The matching ``configs/silver/dags/futures_eod.json`` (the ``gate_baseline_uri`` carrier, 27
    families have one) does not exist yet either; it is a W1a authoring item on the same schedule.

SEED IT AT W1a, alongside the first canonical publish, with:
    python jobs/audit/advance_rolling_census.py --asof <first-publish-date> \
        --dest-uri s3://leviathan-dev-shahem-001/cascade_census/rolling/futures_eod/census.json
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Optional

# Batch invokes this by module (`python -m jobs.audit.advance_rolling_census`) from the repo root, so the
# root is already sys.path[0] and `jobs.*`/`leviathan.*` resolve. Insert defensively anyway (mirrors the
# gate) so a path-form invocation would not break `import jobs.*`.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class ReconcileError(RuntimeError):
    """A reconcile step could not produce/upload a clean rolling baseline. Raised for a malformed dest URI
    or an S3 upload failure; surfaced to the caller as a nonzero exit so the execution FAILS visibly rather
    than leaving a stale baseline. ASCII-only messages."""


# ---------------------------------------------------------------------------
# Seams (each isolates one external dependency so the task unit tests need no
# boto3/network and no live pg/Athena/census run).
# ---------------------------------------------------------------------------
def _s3_client():
    """boto3 S3 client factory. Indirection so tests stub S3 with no boto3/network dependency and module
    import stays AWS-free (boto3 imported lazily here, never at module load)."""
    import boto3

    return boto3.client("s3")


def _run_census(asof: str, out_path: str) -> int:
    """Run the cascade census via the SAME entry point the gate's machinery uses and return its rc.

    Invokes ``cascade_census.main(["--asof", asof, "--json", out_path])`` -- the production live run: it
    asserts GRAPHRAG_NUMBERS_BACKEND=pg + EVIDENCE_PG_DSN, installs the Athena firewall, writes the census
    JSON to ``out_path``, and returns 0 IFF there is no un-waived DARK leg (nonzero on a dirty census; it
    RAISES on a failed env assert / pg outage / firewall trip). Lazy import keeps this module AWS-free and
    light to import; a seam for stubbing in tests."""
    from leviathan.graphrag.numbers import cascade_census

    return cascade_census.main(["--asof", asof, "--json", out_path])


# ---------------------------------------------------------------------------
# S3 destination
# ---------------------------------------------------------------------------
def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Split s3://bucket/key -> (bucket, key). Fail closed (ReconcileError) on a non-s3 scheme or a missing
    bucket/key so a misconfigured dest never silently no-ops."""
    if not uri.startswith("s3://"):
        raise ReconcileError(f"dest-uri must be an s3://bucket/key URI, got: {uri!r}")
    bucket, _, key = uri[len("s3://"):].partition("/")
    if not bucket or not key:
        raise ReconcileError(f"dest-uri is missing a bucket or key: {uri!r}")
    return bucket, key


def _upload(uri: str, data: bytes) -> None:
    """Write the census bytes to the rolling-baseline key. Fail closed (ReconcileError) on any S3 error."""
    bucket, key = _parse_s3_uri(uri)
    try:
        _s3_client().put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/json")
    except Exception as e:  # noqa: BLE001 -- fail closed on ANY S3 error (auth/network/throttle/...)
        raise ReconcileError(
            f"rolling-baseline upload failed for {uri}: {type(e).__name__}: {str(e)[:200]}") from e


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------
def reconcile(asof: str, dest_uri: str) -> int:
    """Re-run the census and roll it forward to the family's rolling S3 baseline. Returns a process exit
    code: 0 on a clean census successfully uploaded, nonzero on ANY failure (fail closed)."""
    asof = str(asof)[:10]  # scheduler may pass <aws.scheduler.scheduled-time> (full ISO) -- truncate to date

    # Validate the destination BEFORE spending a census run on a dest we cannot write to.
    try:
        _parse_s3_uri(dest_uri)
    except ReconcileError as e:
        print(f"FAIL advance_rolling_census: {e}")
        return 1

    with tempfile.TemporaryDirectory(prefix="rolling_census_") as td:
        out_path = str(Path(td) / "census.json")
        try:
            rc = int(_run_census(asof, out_path))
        except Exception as e:  # noqa: BLE001 -- census env assert / pg outage / Athena trip -> fail closed
            print(f"FAIL advance_rolling_census: census run raised: {type(e).__name__}: {str(e)[:200]}")
            return 1
        if rc != 0:
            # A dirty census (un-waived DARK leg) must NOT become the new baseline. Propagate the failure.
            print(f"FAIL advance_rolling_census: census returned nonzero rc={rc} "
                  f"(dirty census -- rolling baseline NOT advanced)")
            return rc
        art = Path(out_path)
        if not art.exists():
            print("FAIL advance_rolling_census: census reported clean but wrote no artifact "
                  f"at {out_path}")
            return 1
        data = art.read_bytes()
        try:
            _upload(dest_uri, data)
        except ReconcileError as e:
            print(f"FAIL advance_rolling_census: {e}")
            return 1

    print(f"advance_rolling_census OK: asof={asof} bytes={len(data)} -> {dest_uri}")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="A-W3 [Reconcile]: roll the run's post-census to the family's rolling S3 baseline")
    ap.add_argument("--asof", required=True,
                    help="census as-of; full ISO timestamps are truncated to the date ([:10]) so the "
                         "scheduler's <aws.scheduler.scheduled-time> context attribute works")
    ap.add_argument("--dest-uri", required=True,
                    help="s3://bucket/key of the family's rolling baseline census.json to (over)write "
                         "(the same key the next gate reads via --baseline-uri)")
    a = ap.parse_args(argv)
    return reconcile(a.asof, a.dest_uri)


if __name__ == "__main__":
    sys.exit(main())
