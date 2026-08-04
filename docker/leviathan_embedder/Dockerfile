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

# FENCE (incident I-1): build provenance, injected as ARGs because .dockerignore excludes .git.
# This image matters to the fence specifically because the MANUAL gate path
# (jobs/submit/submit_batch_silver_rebuild_gate.py:34) targets leviathan-dev-evidence-build.
#
# CACHE FENCE (2026-08-04): declared HERE, immediately above their ONLY consumer, and never at the
# top of the file. An ARG is in scope for every instruction that FOLLOWS it, and Docker keys a
# following RUN as though the arg were in that command's environment -- so a value that changes
# every commit (BUILD_GIT_COMMIT does) invalidates that RUN even though the command never names
# it. At the top of the file these two sat above the torch-CPU + [embed,pg,serve] pip layer, which
# is the ~2 GB bulk of this image (see the header note on why the model is NOT baked in), and
# forced it to rebuild and re-upload on every commit through the proxy that breaks the pipe on GB
# PUTs. Below it, that layer's cache key depends only on the base image, the apt set and
# pyproject.toml.
# This paragraph is NOT the fence -- the fence is
# tests/unit/test_image_config_fence.py::test_provenance_args_stay_below_the_heavy_layers, which
# fails if either ARG is moved above the torch/[embed] pip RUN.
ARG BUILD_GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

# Stamp AFTER `COPY configs/` (stamping earlier fingerprints an empty dir).
RUN BUILD_GIT_COMMIT="$BUILD_GIT_COMMIT" BUILD_TIME="$BUILD_TIME" \
    python -m leviathan.common.image_stamp --write /app/IMAGE_MANIFEST.json

ENTRYPOINT ["python"]
