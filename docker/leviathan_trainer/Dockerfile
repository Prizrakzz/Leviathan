FROM python:3.11-slim

WORKDIR /app

# Runtime libs only: libgomp1 for XGBoost/LightGBM OpenMP, libcurl4 for curl-cffi,
# libexpat1 for the stdlib XML parser.  No gcc/python3-dev — the [training] deps ship
# prebuilt manylinux wheels, nothing compiles at install time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
        libgomp1 \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

# Lean tree-model trainer: xgboost/lightgbm/sklearn/mlflow/optuna only.
# torch + shap live in the [training-dl] extra and a separate image (see pyproject).
RUN pip install --no-cache-dir -e ".[training]"

ENTRYPOINT ["python"]
