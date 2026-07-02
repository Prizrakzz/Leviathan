"""Attach a scoped Athena + Glue-catalog-read inline policy to the Batch task role (GraphRAG numbers agent).

The numbers SQL agent runs Athena queries against the silver data lake. The Batch TASK role
(``leviathan-dev-batch-job-role``) already has full R/W on the bucket (so Athena's S3 result-write + Parquet-read
are covered) but NO ``athena:*`` and no Glue catalog read. This adds ONLY those — read-only catalog metadata + the
query-execution verbs — as a self-documenting inline policy that's trivially removable (``delete_role_policy``).
This is exactly what the numbers agent needs cloud-side in production too, so it's not throwaway.

    python jobs/utils/attach_numbers_athena_policy.py             # DRY-RUN: print the policy, attach nothing
    python jobs/utils/attach_numbers_athena_policy.py --attach    # attach it (idempotent put_role_policy)
"""
from __future__ import annotations

import argparse
import json

import boto3

_ROLE = "leviathan-dev-batch-job-role"
_POLICY_NAME = "leviathan-dev-numbers-athena"

_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {"Sid": "AthenaQuery", "Effect": "Allow", "Action": [
            "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
            "athena:StopQueryExecution", "athena:GetWorkGroup"], "Resource": "*"},
        {"Sid": "GlueCatalogRead", "Effect": "Allow", "Action": [
            "glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables",
            "glue:GetPartition", "glue:GetPartitions"], "Resource": "*"},
        # Athena validates its query-results output bucket via GetBucketLocation. The role's S3 policy has
        # ListBucket + Put/Get/Delete but NOT this -> "Unable to verify/create output bucket". (Confirmed via a
        # Fargate diagnostic: StartQueryExecution failed with exactly this until GetBucketLocation was added.)
        {"Sid": "AthenaResultsBucket", "Effect": "Allow", "Action": ["s3:GetBucketLocation"],
         "Resource": "arn:aws:s3:::leviathan-dev-shahem-001"},
    ],
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Attach the numbers-agent Athena/Glue-read policy to the Batch task role.")
    ap.add_argument("--attach", action="store_true", help="actually attach (default is dry-run)")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()
    print(f"role: {_ROLE}\npolicy: {_POLICY_NAME}\n{json.dumps(_POLICY, indent=2)}")
    if not args.attach:
        print("\n[DRY-RUN] nothing attached. Re-run with --attach to apply.")
        return
    iam = boto3.client("iam", region_name=args.region)
    iam.put_role_policy(RoleName=_ROLE, PolicyName=_POLICY_NAME, PolicyDocument=json.dumps(_POLICY))
    print(f"\nattached inline policy {_POLICY_NAME} to {_ROLE} (S3 already covered by leviathan-dev-s3-data-lake-rw).")


if __name__ == "__main__":
    main()
