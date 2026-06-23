"""Capture a deterministic logical inventory of the live Leviathan ML system."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from leviathan.audit.system_inventory import json_document, parquet_rows  # noqa: E402
from leviathan.ops.ml_platform import canonical_json_bytes, utc_backup_id  # noqa: E402


EXPAND_DATASET_PREFIXES = {
    "silver/fnc_colombia/",
    "silver/production/",
    "silver/weather/",
    "gold/feature_matrix/",
    "gold/feature_spine/",
}


def common_prefixes(s3, bucket: str, prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    values: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        values.extend(item["Prefix"] for item in page.get("CommonPrefixes", []))
    return sorted(set(values))


def discover_datasets(s3, bucket: str) -> list[tuple[str, str]]:
    datasets: list[tuple[str, str]] = []
    for layer in ("silver", "gold"):
        for child in common_prefixes(s3, bucket, f"{layer}/"):
            if child in EXPAND_DATASET_PREFIXES:
                nested = common_prefixes(s3, bucket, child)
                if nested:
                    datasets.extend((layer, value) for value in nested)
                    continue
            datasets.append((layer, child))
    for prefix in ("mlflow/", "model_artifacts/", "quality/"):
        datasets.append(("operations", prefix))
    return sorted(set(datasets))


def summarize_prefix_objects(
    s3,
    bucket: str,
    prefix: str,
    *,
    exact_row_count_limit: int,
    schema_sample_limit: int,
) -> dict[str, Any]:
    object_count = 0
    total_size_bytes = 0
    first_key = None
    last_key = None
    latest_modified = None
    storage_classes: dict[str, int] = {}
    parquet_count = 0
    retained_parquet_keys: list[str] = []
    retain_limit = max(exact_row_count_limit, schema_sample_limit)
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            modified = item["LastModified"].isoformat()
            object_count += 1
            total_size_bytes += int(item["Size"])
            first_key = first_key or key
            last_key = key
            latest_modified = max(latest_modified or modified, modified)
            storage_class = item.get("StorageClass", "STANDARD")
            storage_classes[storage_class] = storage_classes.get(storage_class, 0) + 1
            if key.endswith(".parquet"):
                parquet_count += 1
                if len(retained_parquet_keys) < retain_limit:
                    retained_parquet_keys.append(key)
    return {
        "object_count": object_count,
        "total_size_bytes": total_size_bytes,
        "first_key": first_key,
        "last_key": last_key,
        "latest_modified": latest_modified,
        "storage_class_counts": dict(sorted(storage_classes.items())),
        **parquet_summary(
            s3,
            bucket,
            retained_parquet_keys,
            parquet_count=parquet_count,
            exact_row_count_limit=exact_row_count_limit,
            schema_sample_limit=schema_sample_limit,
        ),
    }


def parquet_summary(
    s3,
    bucket: str,
    retained_keys: list[str],
    *,
    parquet_count: int,
    exact_row_count_limit: int,
    schema_sample_limit: int,
) -> dict[str, Any]:
    schema_hashes: set[str] = set()
    schemas: list[list[dict[str, str]]] = []
    exact_rows = 0
    exact = parquet_count <= exact_row_count_limit
    read_count = parquet_count if exact else min(parquet_count, schema_sample_limit)
    for key in retained_keys[:read_count]:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        metadata = pq.ParquetFile(io.BytesIO(body))
        if exact:
            exact_rows += int(metadata.metadata.num_rows)
        schema = [
            {"name": field.name, "type": str(field.type)}
            for field in metadata.schema_arrow
        ]
        digest = hashlib.sha256(canonical_json_bytes(schema)).hexdigest()
        if digest not in schema_hashes:
            schema_hashes.add(digest)
            schemas.append(schema)
    return {
        "parquet_file_count": parquet_count,
        "row_count": exact_rows if exact else None,
        "row_count_status": "exact" if exact else "skipped_large_dataset",
        "schema_sample_file_count": read_count,
        "distinct_sampled_schema_count": len(schema_hashes),
        "sampled_schema_sha256": sorted(schema_hashes),
        "sampled_schemas": schemas,
    }


def latest_cloudwatch_datapoint(cloudwatch, metric: str, bucket: str, storage: str) -> dict:
    now = datetime.now(timezone.utc)
    end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    response = cloudwatch.get_metric_statistics(
        Namespace="AWS/S3",
        MetricName=metric,
        Dimensions=[
            {"Name": "BucketName", "Value": bucket},
            {"Name": "StorageType", "Value": storage},
        ],
        StartTime=end - timedelta(days=7),
        EndTime=end,
        Period=86400,
        Statistics=["Average"],
    )
    points = sorted(response.get("Datapoints", []), key=lambda value: value["Timestamp"])
    if not points:
        return {}
    point = points[-1]
    return {
        "timestamp": point["Timestamp"].isoformat(),
        "average": point["Average"],
        "unit": point["Unit"],
    }


def s3_root_records(s3, bucket: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for root in common_prefixes(s3, bucket, ""):
        records.append({"prefix": root, "kind": "root"})
    for parent in ("raw/production/", "raw/weather/", "bronze/production/", "bronze/weather/"):
        for prefix in common_prefixes(s3, bucket, parent):
            records.append({"prefix": prefix, "kind": "logical_source"})
    return records


def glue_records(glue, database: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    paginator = glue.get_paginator("get_tables")
    for page in paginator.paginate(DatabaseName=database):
        for table in page["TableList"]:
            descriptor = table.get("StorageDescriptor", {})
            records.append({
                "database": database,
                "name": table["Name"],
                "location": descriptor.get("Location"),
                "columns": [
                    {"name": col["Name"], "type": col["Type"]}
                    for col in descriptor.get("Columns", [])
                ],
                "partition_keys": [
                    {"name": col["Name"], "type": col["Type"]}
                    for col in table.get("PartitionKeys", [])
                ],
                "projection_enabled": table.get("Parameters", {}).get(
                    "projection.enabled", "false"
                ),
            })
    return records


def batch_records(batch) -> list[dict[str, Any]]:
    response = batch.describe_job_definitions(status="ACTIVE")
    records: list[dict[str, Any]] = []
    for job in response["jobDefinitions"]:
        container = job.get("containerProperties", {})
        records.append({
            "name": job["jobDefinitionName"],
            "revision": int(job["revision"]),
            "arn": job["jobDefinitionArn"],
            "image": container.get("image"),
            "command": container.get("command", []),
            "resource_requirements": container.get("resourceRequirements", []),
            "parameters": job.get("parameters", {}),
        })
    return records


def ecr_records(ecr) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for repository in ecr.describe_repositories()["repositories"]:
        name = repository["repositoryName"]
        if "leviathan" not in name:
            continue
        paginator = ecr.get_paginator("describe_images")
        for page in paginator.paginate(repositoryName=name):
            for image in page.get("imageDetails", []):
                records.append({
                    "repository": name,
                    "digest": image["imageDigest"],
                    "tags": sorted(image.get("imageTags", [])),
                    "pushed_at": image.get("imagePushedAt").isoformat()
                    if image.get("imagePushedAt") else None,
                    "size_bytes": int(image.get("imageSizeInBytes", 0)),
                })
    return records


def ec2_records(ec2, instance_id: str) -> tuple[list[dict], list[dict]]:
    response = ec2.describe_instances(InstanceIds=[instance_id])
    instances: list[dict] = []
    volume_ids: list[str] = []
    for reservation in response["Reservations"]:
        for item in reservation["Instances"]:
            volume_ids.extend(
                mapping["Ebs"]["VolumeId"]
                for mapping in item.get("BlockDeviceMappings", [])
                if "Ebs" in mapping
            )
            instances.append({
                "instance_id": item["InstanceId"],
                "state": item["State"]["Name"],
                "instance_type": item["InstanceType"],
                "ami": item["ImageId"],
                "private_ip": item.get("PrivateIpAddress"),
                "subnet_id": item.get("SubnetId"),
                "security_group_ids": sorted(
                    value["GroupId"] for value in item.get("SecurityGroups", [])
                ),
                "iam_instance_profile": (
                    item.get("IamInstanceProfile") or {}
                ).get("Arn"),
            })
    volumes: list[dict] = []
    if volume_ids:
        for volume in ec2.describe_volumes(VolumeIds=volume_ids)["Volumes"]:
            volumes.append({
                "volume_id": volume["VolumeId"],
                "size_gib": int(volume["Size"]),
                "volume_type": volume["VolumeType"],
                "encrypted": bool(volume["Encrypted"]),
                "state": volume["State"],
                "delete_on_termination": next(
                    (
                        mapping["Ebs"].get("DeleteOnTermination")
                        for reservation in response["Reservations"]
                        for instance in reservation["Instances"]
                        for mapping in instance.get("BlockDeviceMappings", [])
                        if mapping.get("Ebs", {}).get("VolumeId") == volume["VolumeId"]
                    ),
                    None,
                ),
            })
    return instances, volumes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=os.getenv("LEVIATHAN_BUCKET"))
    parser.add_argument("--aws-region", default=os.getenv("AWS_REGION", "us-east-1"))
    parser.add_argument("--glue-database", default="leviathan_dev")
    parser.add_argument("--ml-instance-id", required=True)
    parser.add_argument("--run-id", default=utc_backup_id())
    parser.add_argument("--as-of-date")
    parser.add_argument("--exact-row-count-limit", type=int, default=100)
    parser.add_argument("--schema-sample-limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--output-dir", type=Path, default=Path("data/system_inventory"))
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()
    if not args.bucket:
        raise SystemExit("--bucket or LEVIATHAN_BUCKET is required")

    generated = datetime.now(timezone.utc)
    as_of_date = args.as_of_date or generated.date().isoformat()
    session = boto3.session.Session(region_name=args.aws_region)
    s3 = session.client("s3")
    discovered = discover_datasets(s3, args.bucket)

    def scan_dataset(dataset: tuple[str, str]) -> dict[str, Any]:
        layer, prefix = dataset
        return {
            "layer": layer,
            "prefix": prefix,
            **summarize_prefix_objects(
                s3,
                args.bucket,
                prefix,
                exact_row_count_limit=args.exact_row_count_limit,
                schema_sample_limit=args.schema_sample_limit,
            ),
        }

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        datasets = list(executor.map(scan_dataset, discovered))

    ec2_instances, ebs_volumes = ec2_records(
        session.client("ec2"), args.ml_instance_id
    )
    cloudwatch = session.client("cloudwatch")
    content = {
        "aws_account_id": session.client("sts").get_caller_identity()["Account"],
        "aws_region": args.aws_region,
        "s3_bucket": args.bucket,
        "s3_bucket_metrics": {
            "number_of_objects": latest_cloudwatch_datapoint(
                cloudwatch, "NumberOfObjects", args.bucket, "AllStorageTypes"
            ),
            "standard_storage_bytes": latest_cloudwatch_datapoint(
                cloudwatch, "BucketSizeBytes", args.bucket, "StandardStorage"
            ),
        },
        "s3_root_prefixes": s3_root_records(s3, args.bucket),
        "s3_datasets": datasets,
        "glue_tables": glue_records(session.client("glue"), args.glue_database),
        "batch_job_definitions": batch_records(session.client("batch")),
        "ecr_images": ecr_records(session.client("ecr")),
        "ec2_instances": ec2_instances,
        "ebs_volumes": ebs_volumes,
    }
    document = json_document(
        run_id=args.run_id,
        generated_at=generated.isoformat(),
        content=content,
    )
    output_dir = args.output_dir / f"as_of_date={as_of_date}" / f"run_id={args.run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "inventory.json"
    parquet_path = output_dir / "inventory_datasets.parquet"
    json_path.write_bytes(canonical_json_bytes(document))
    pd.DataFrame(parquet_rows(content)).to_parquet(parquet_path, index=False)

    uris = {}
    if not args.no_upload:
        prefix = (
            f"metadata/system_inventory/as_of_date={as_of_date}/"
            f"run_id={args.run_id}"
        )
        for path in (json_path, parquet_path):
            key = f"{prefix}/{path.name}"
            s3.upload_file(str(path), args.bucket, key)
            uris[path.name] = f"s3://{args.bucket}/{key}"
    print(json.dumps({
        "logical_content_sha256": document["logical_content_sha256"],
        "local_json": str(json_path.resolve()),
        "local_parquet": str(parquet_path.resolve()),
        "s3": uris,
        "dataset_count": len(datasets),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
