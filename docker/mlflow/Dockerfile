# leviathan_mlflow -- MLflow tracking server for the EC2 -> Fargate relocation (module.mlflow_fargate).
#
# WHY THIS IMAGE EXISTS: the Fargate task previously ran ghcr.io/mlflow/mlflow:v3.14.0 with a boot-time
# `/bin/sh -c "pip install psycopg2-binary boto3 && exec mlflow server ..."`. That runtime install failed
# and the container crashlooped with NO logs. Everything the server needs is BAKED here so NOTHING is
# installed at container boot -- the entrypoint runs only `mlflow server`.
#
# VERSION LOCK: mlflow==3.14.0 MUST match the trainer client (pyproject `mlflow==3.14.0`,
# docker/leviathan_trainer) so the tracking server and the client speak the same REST/schema. Do not
# bump in isolation.
FROM python:3.11-slim

WORKDIR /app

# Backend store = Postgres (psycopg2-binary bundles its own libpq -- no apt layer needed); artifact root
# = S3 (boto3); gunicorn is the WSGI server `mlflow server` runs behind. Pinned so the layer is
# reproducible and boot never touches PyPI.
RUN pip install --no-cache-dir \
        "mlflow==3.14.0" \
        "psycopg2-binary>=2.9" \
        "boto3" \
        "gunicorn"

# Run as a non-root user: the server installs nothing at boot and keeps no local state (backend is
# Postgres, artifacts are S3), so it needs no privileges.
RUN useradd --create-home --uid 10001 mlflow
USER mlflow

EXPOSE 5000

# Clean baked entrypoint -- ONLY `mlflow server`. `exec` makes mlflow PID 1 (clean SIGTERM on task stop).
# $MLFLOW_BACKEND_STORE_URI (Secrets Manager -> ECS secret) and $MLFLOW_DEFAULT_ARTIFACT_ROOT (ECS env)
# are injected by the task definition and expanded by the shell. NO runtime pip.
ENTRYPOINT ["/bin/sh", "-c", "exec mlflow server --backend-store-uri \"$MLFLOW_BACKEND_STORE_URI\" --default-artifact-root \"$MLFLOW_DEFAULT_ARTIFACT_ROOT\" --host 0.0.0.0 --port 5000"]
