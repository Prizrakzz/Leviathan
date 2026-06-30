# leviathan_embedder — the evidence-build worker (GraphRAG v2 WS-MS2).
# Bedrock-Haiku propositional chunking + SELF-HOSTED bge-m3 embeddings (there is no bge-m3 on Bedrock).
# Kept separate from leviathan_worker so torch + sentence-transformers + the baked bge-m3 model (~2.5 GB) don't
# bloat every other Batch job. bge-m3 runs on CPU across the task's vCPUs (Fargate has no GPU).
FROM python:3.11-slim

WORKDIR /app

# libgomp1 for torch/sentence-transformers OpenMP; the others mirror leviathan_worker (rasterio in .[batch]).
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

# Dependencies first (this large layer caches unless pyproject.toml changes). torch is the CPU-only wheel from
# the PyTorch CPU index; the subsequent .[batch,embed] install sees torch already satisfied and won't change it.
COPY pyproject.toml ./
RUN mkdir -p src/leviathan && touch src/leviathan/__init__.py && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -e ".[batch,embed]"

# Pre-download bge-m3 into /opt/hf (temporarily online; the runtime stays offline via the ENV above).
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# Real source last — small layers on change. configs/ carries the gitignored causal DAG + evidence_windows.yaml
# (Docker copies the filesystem, not git); they stay inside this PRIVATE ECR image.
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

ENTRYPOINT ["python"]
