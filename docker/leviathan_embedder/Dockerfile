# leviathan_embedder — the evidence-build worker (GraphRAG v2 WS-MS2).
# Bedrock-Haiku propositional chunking + SELF-HOSTED bge-m3 embeddings (there is no bge-m3 on Bedrock).
# Kept separate from leviathan_worker so torch + sentence-transformers + the baked bge-m3 model don't bloat
# every other Batch job. bge-m3 runs on CPU across the task's vCPUs (Fargate has no GPU).
#
# Layer order is deliberate: torch + sentence-transformers, THEN the bge-m3 download, THEN the project deps.
# So an ordinary code/pyproject change rebuilds only the cheap tail layers and the ~2 GB model download stays
# cached. The evidence task needs core + pydantic + [embed] only — NOT [batch] (rasterio/GDAL/pdf are unused).
FROM python:3.11-slim

WORKDIR /app

# libgomp1 for torch/sentence-transformers OpenMP; libcurl4 for the curl-cffi core dep; libexpat1 is cheap.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
        libgomp1 \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

# bge-m3 is baked into a fixed cache dir and read OFFLINE at runtime (no HF download in the Batch job).
ENV HF_HOME=/opt/hf \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    PYTHONIOENCODING=utf-8

# 1) Stable heavy layer: torch (CPU-only wheel from the PyTorch CPU index) + sentence-transformers.
#    Re-runs only when these pins change — not on ordinary code/pyproject edits.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir "sentence-transformers>=2.2"

# 2) Bake bge-m3 (temporarily online; runtime stays offline via the ENV above). Cached above the project deps,
#    so a dependency change does NOT re-download the model.
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# 3) Project dependencies: core (incl. pydantic) + [embed]. torch + sentence-transformers are already satisfied.
COPY pyproject.toml ./
RUN mkdir -p src/leviathan && touch src/leviathan/__init__.py && \
    pip install --no-cache-dir -e ".[embed]"

# 4) Real source last — small layers on change. configs/ carries the gitignored causal DAG + evidence_windows.yaml
#    (Docker copies the filesystem, not git); they stay inside this PRIVATE ECR image. .dockerignore excludes the
#    469 MB configs/graphrag/evidence/ (regenerated in S3) + the eval/pilot report dirs.
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

ENTRYPOINT ["python"]
