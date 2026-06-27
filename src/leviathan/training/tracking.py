"""Reproducibility tracking for MLflow training runs.

Closes the two data-versioning layers that make an experiment auditable, without
standing up a SageMaker Feature Store:

  Layer 2 — feature-set identity:   ``feature_set_sha`` over the exact feature
            columns + the registry params hash.  You only compare runs with the
            same SHA, never apples to oranges.
  Layer 1 — data identity / vintage: ``data_fingerprint`` over the exact training
            slice (revision detector — if a FAOSTAT revision silently changes a
            value on the next spine rebuild, the fingerprint changes), plus an
            optional immutable ``snapshot`` of the slice to S3.

``log_training_run`` ties these to the cv.py / slices.py outputs and writes them
to the active MLflow run.  The pure functions have no MLflow dependency so they
are unit-tested in isolation; MLflow is imported lazily only when logging.
"""
from __future__ import annotations

import hashlib
import io
import json
import re

import pandas as pd

_KEY_COLS = ["country", "crop_year"]
_OPTIONAL_KEY_COLS = ["snapshot_stage", "as_of_date"]


# ---------------------------------------------------------------------------
# Pure identity functions
# ---------------------------------------------------------------------------

def feature_set_sha(feature_cols: list[str], params_hash: str) -> str:
    """Deterministic identity of a feature set: sorted columns + params hash.

    Two runs that feed the model the same columns under the same
    feature_params.yaml get the same SHA; changing either changes it.
    """
    payload = "|".join(sorted(feature_cols)) + "::" + str(params_hash or "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _key_cols(df: pd.DataFrame) -> list[str]:
    return _KEY_COLS + [col for col in _OPTIONAL_KEY_COLS if col in df.columns]


def data_fingerprint(
    df: pd.DataFrame, feature_cols: list[str], target_col: str
) -> str:
    """Content hash of the exact training slice.

    Canonicalised (rows sorted by the natural key, columns in a fixed order) so
    the digest is stable under row/column reordering but changes whenever any
    value — feature or label — changes.  This is what surfaces a silent upstream
    revision between two rebuilds of the same logical dataset.
    """
    key_cols = _key_cols(df)
    cols = key_cols + sorted(c for c in feature_cols if c in df.columns)
    if target_col in df.columns:
        cols.append(target_col)
    sub = df.loc[:, cols].sort_values(key_cols).reset_index(drop=True)
    row_hashes = pd.util.hash_pandas_object(sub, index=False).to_numpy()
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# Spine provenance + immutable snapshot
# ---------------------------------------------------------------------------

def load_spine_provenance(
    bucket: str, commodity: str, *, aws_region: str | None = None
) -> dict:
    """Read the gold spine run manifest for traceability tags.

    Returns ``{}`` when no manifest exists.  ``spine_input_fingerprint`` is a
    short digest of the silver input fingerprints the partition was built from.
    """
    import boto3

    s3 = boto3.client("s3", region_name=aws_region)
    key = f"gold/feature_spine/_manifests/commodity={commodity}/run.json"
    try:
        manifest = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
    except Exception:  # noqa: BLE001 — missing/unreadable manifest is non-fatal
        return {}

    inputs = manifest.get("inputs") or []
    input_fp = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "spine_params_hash": manifest.get("params_hash"),
        "spine_git_sha": manifest.get("git_sha"),
        "spine_built_at": manifest.get("built_at"),
        "spine_input_fingerprint": input_fp,
        "matrix_key": manifest.get("matrix_key"),
    }


def snapshot_training_data(
    df: pd.DataFrame, bucket: str, run_id: str, commodity: str,
    *, aws_region: str | None = None, snapshot_name: str | None = None,
) -> str:
    """Freeze the training slice to an immutable S3 path; return its URI."""
    import boto3

    s3 = boto3.client("s3", region_name=aws_region)
    name = snapshot_name or commodity
    safe_name = re.sub(r"[^A-Za-z0-9_.=-]+", "_", name).strip("_") or commodity
    key = f"model_artifacts/training_snapshots/{run_id}/{safe_name}.parquet"
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow", compression="snappy")
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


# ---------------------------------------------------------------------------
# MLflow orchestration
# ---------------------------------------------------------------------------

def log_training_run(
    commodity: str,
    tier: str,
    train_df: pd.DataFrame,
    feature_cols: list[str],
    result,
    *,
    target_col: str,
    params_hash: str | None = None,
    bucket: str | None = None,
    aws_region: str | None = None,
    mlflow=None,
    snapshot: bool = True,
    gaps: pd.DataFrame | None = None,
    extra_tags: dict[str, object] | None = None,
    extra_params: dict[str, object] | None = None,
    snapshot_name: str | None = None,
) -> dict:
    """Log a walk-forward run to MLflow with full reproducibility metadata.

    Tags: commodity, tier, feature_set_sha, data_fingerprint, snapshot_uri, and
    the spine provenance (params hash, build time, input fingerprint).
    Params: feature / row counts and the train window.
    Metrics: ``result.as_mlflow_metrics()`` (aggregate + the per-slice metrics)
    plus ``gaps_passed`` and per-rule statuses when a gaps frame is supplied.

    Returns the metadata dict it logged (handy for tests / inspection).  Pass a
    stand-in ``mlflow`` for testing; otherwise it is imported lazily.
    """
    if mlflow is None:
        import mlflow as mlflow  # noqa: PLC0414 — lazy import, no top-level dep

    prov = load_spine_provenance(bucket, commodity, aws_region=aws_region) if bucket else {}
    resolved_params_hash = params_hash or prov.get("spine_params_hash") or ""

    fs_sha = feature_set_sha(feature_cols, resolved_params_hash)
    data_fp = data_fingerprint(train_df, feature_cols, target_col)
    years = sorted(int(y) for y in train_df["crop_year"].dropna().unique()) \
        if "crop_year" in train_df.columns else []

    tags: dict[str, str] = {
        "commodity": commodity,
        "tier": tier,
        "feature_set_sha": fs_sha,
        "data_fingerprint": data_fp,
    }
    for key, value in (extra_tags or {}).items():
        if value is not None:
            tags[str(key)] = str(value)
    for key in ("spine_params_hash", "spine_git_sha", "spine_built_at",
                "spine_input_fingerprint"):
        if prov.get(key) is not None:
            tags[key] = str(prov[key])

    if snapshot and bucket:
        run = mlflow.active_run()
        run_id = run.info.run_id if run is not None else "no-active-run"
        tags["snapshot_uri"] = snapshot_training_data(
            train_df, bucket, run_id, commodity,
            aws_region=aws_region, snapshot_name=snapshot_name,
        )

    params = {
        "n_features": len(feature_cols),
        "n_train_rows": int(len(train_df)),
        "train_first_year": years[0] if years else None,
        "train_last_year": years[-1] if years else None,
    }
    for key, value in (extra_params or {}).items():
        if value is not None:
            params[str(key)] = value

    for key, value in tags.items():
        mlflow.set_tag(key, value)
    for key, value in params.items():
        if value is not None:
            mlflow.log_param(key, value)
    mlflow.log_metrics(result.as_mlflow_metrics())

    if gaps is not None and not gaps.empty:
        from leviathan.training.slices import gaps_passed
        mlflow.log_metric("gaps_passed", float(gaps_passed(gaps)))
        for _, r in gaps.iterrows():
            mlflow.set_tag(f"gap_{r['rule']}", r["status"])

    return {"tags": tags, "params": params,
            "feature_set_sha": fs_sha, "data_fingerprint": data_fp}
