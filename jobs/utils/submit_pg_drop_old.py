"""Owner-run: drop the pre-X2 rollback artifact evidence_props_old (ratified; gate passed).

The rev-108 canary passed 2026-08-20 23:22 local, which was the retained table's stated drop
gate ("rollback artifact, drops after rev-108 canary parity"). Dropping it now frees ~4-5 GB of
RDS headroom ahead of the completion wave's blue-green load — the exact headroom whose absence
hit the disk wall on 2026-08-20.

Fail-closed: the in-VPC job refuses the drop unless the LIVE table holds exactly the swapped
count (1,277,979). Runs on the evidence-build jobdef (rev 81), which carries EVIDENCE_PG_DSN as
a secret; RDS is unreachable from the laptop.

    python jobs/utils/submit_pg_drop_old.py
"""
from __future__ import annotations

import boto3

CODE = """
import os, psycopg
conn = psycopg.connect(os.environ["EVIDENCE_PG_DSN"], autocommit=True, connect_timeout=20)
row = conn.execute("SELECT to_regclass('evidence_props_old') IS NOT NULL").fetchone()
if not row[0]:
    print("evidence_props_old ABSENT -- nothing to drop", flush=True)
else:
    n = conn.execute("SELECT count(*) FROM evidence_props").fetchone()[0]
    if n != 1277979:
        print("REFUSING drop: live evidence_props =", n, "!= expected 1277979", flush=True)
        raise SystemExit(1)
    old_n = conn.execute("SELECT count(*) FROM evidence_props_old").fetchone()[0]
    sz = conn.execute("SELECT pg_size_pretty(pg_total_relation_size('evidence_props_old'))").fetchone()[0]
    conn.execute("DROP TABLE evidence_props_old")
    print("DROPPED evidence_props_old:", old_n, "rows,", sz, "-- live verified at", n, flush=True)
db = conn.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
print("database size now:", db, flush=True)
"""


def main() -> None:
    client = boto3.client("batch", region_name="us-east-1")
    resp = client.submit_job(
        jobName="pg-drop-evidence-props-old",
        jobQueue="leviathan-dev-queue-ondemand",
        jobDefinition="leviathan-dev-evidence-build:81",
        containerOverrides={
            "command": ["-c", CODE],
            "resourceRequirements": [{"type": "VCPU", "value": "1"}, {"type": "MEMORY", "value": "2048"}],
        })
    print("submitted pg-drop-evidence-props-old  job_id=" + resp["jobId"])
    print("check:  aws batch describe-jobs --jobs " + resp["jobId"] + " --region us-east-1 "
          "--query jobs[0].status --output text")


if __name__ == "__main__":
    main()
