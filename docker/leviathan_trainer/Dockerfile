FROM python:3.11-slim

WORKDIR /app

# Runtime libs only: libgomp1 for XGBoost/LightGBM OpenMP and libexpat1 for
# the stdlib XML parser. No gcc/python3-dev: the trainer deps ship prebuilt
# manylinux wheels, nothing compiles at install time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

# Lean tree-model trainer:
# - install project code without full project deps; ingestion/parser deps are
#   not needed for jobs/batch/train_commodity.py.
# - use mlflow-skinny; this container is an MLflow client, not a server.
# - remove xgboost's optional NVIDIA NCCL wheel. Batch uses CPU tree models,
#   and XGBoost still imports/trains without the GPU payload.
RUN pip install --no-cache-dir --no-compile --upgrade pip \
    && pip install --no-cache-dir --no-compile -e . --no-deps \
    && pip install --no-cache-dir --no-compile \
        boto3 \
        "lightgbm>=4.0" \
        "mlflow-skinny>=2.9" \
        numpy \
        "optuna>=3.5" \
        pandas \
        pyarrow \
        pyyaml \
        "scikit-learn>=1.3" \
        "xgboost>=2.0" \
    && (pip uninstall -y nvidia-nccl-cu12 || true) \
    && rm -rf \
        /usr/local/lib/python3.11/site-packages/nvidia \
        /usr/local/lib/python3.11/site-packages/nvidia_nccl* \
        /usr/local/lib/python3.11/site-packages/pandas/tests \
        /usr/local/lib/python3.11/site-packages/pyarrow/tests \
        /usr/local/lib/python3.11/site-packages/sklearn/tests \
        /usr/local/lib/python3.11/site-packages/matplotlib/tests \
    && find /usr/local/lib/python3.11/site-packages -type d -name "__pycache__" -prune -exec rm -rf {} + \
    && find /usr/local/lib/python3.11/site-packages -type f -name "*.pyc" -delete

ENTRYPOINT ["python"]
