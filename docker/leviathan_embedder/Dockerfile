# leviathan_embedder — the evidence-build worker (GraphRAG v2 WS-MS2).
# Bedrock-Haiku propositional chunking + self-hosted bge-m3 embeddings (there is no bge-m3 on Bedrock).
# Kept separate from leviathan_worker so torch + sentence-transformers don't bloat every other Batch job.
# bge-m3 runs on CPU across the task's vCPUs (Fargate has no GPU).
#
# The bge-m3 MODEL IS NOT BAKED IN — the task downloads it from HuggingFace into /opt/hf on first use (in-AWS,
# fast). Baking the ~4.5 GB model produced a ~10 GB image whose large layer blob could not be pushed reliably
# from the laptop (Docker Desktop proxy broke the pipe). A model-less image is ~2 GB — pushes like the worker
# image — and the runtime download is fast + in-region. (A future hardening can cache the model in S3.)
FROM python:3.11-slim

WORKDIR /app

# libgomp1 for torch/sentence-transformers OpenMP; libcurl4 for the curl-cffi core dep; libexpat1 is cheap.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
        libgomp1 \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

# HF cache dir (writable at runtime); ONLINE so the task can fetch bge-m3 on first use.
ENV HF_HOME=/opt/hf \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf \
    TOKENIZERS_PARALLELISM=false \
    PYTHONIOENCODING=utf-8

# torch CPU-only wheel from the PyTorch CPU index, then the project deps (core + [embed] = sentence-transformers).
# torch is installed first so the [embed] resolution sees it satisfied and won't pull the CUDA build.
COPY pyproject.toml ./
RUN mkdir -p src/leviathan && touch src/leviathan/__init__.py && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -e ".[embed,pg,serve]"
# [serve] adds langgraph + fastapi + uvicorn (~10 MB): this same image now also runs the UI backend
# as an ECS service —  python -m uvicorn leviathan.graphrag.server:app --host 0.0.0.0 --port 8080

# Real source last — small layers on change. configs/ carries the gitignored causal DAG + evidence_windows.yaml
# + driver_slices.yaml (Docker copies the filesystem, not git); they stay inside this PRIVATE ECR image.
# .dockerignore excludes the 469 MB configs/graphrag/evidence/ (regenerated in S3) + the eval/pilot report dirs.
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/
# offline gate scripts (chain_pit_backtest, pace_soak_report, mini-deck gen) run in-container
COPY scripts/ ./scripts/
# sql/ carries the generated Athena DDLs: the silver_rebuild_gate's config_check stage lints the
# node_silver_map against them IN-VPC (DDL-not-found false-RED at the first Branch-A fire without it).
COPY sql/ ./sql/

ENTRYPOINT ["python"]
