FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
        libgomp1 \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

# Install torch CPU-only wheel before the package extras so pip does not pull
# the multi-GB CUDA distribution from PyPI when resolving [training] deps.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -e ".[training]"

# SageMaker Training Jobs pass hyperparameters as SM_HP_* environment variables
# (handled by sagemaker-training toolkit) and expect the model artifact written
# to /opt/ml/model/.  No Dockerfile changes needed for this — the training
# script reads SM_HP_* directly and writes to /opt/ml/model/.
RUN mkdir -p /opt/ml/model /opt/ml/output

ENTRYPOINT ["python"]
