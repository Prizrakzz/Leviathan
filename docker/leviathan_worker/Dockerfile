FROM python:3.11-slim

# FENCE (incident I-1): build provenance. .dockerignore excludes .git, so NO image can ever run
# `git rev-parse` on itself (this is exactly why jobs/batch/pattern_records_sweep_task.py:219-225
# falls back to "unknown"). The commit MUST be injected as a build ARG by the build script.
ARG BUILD_GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

WORKDIR /app

# System libraries required by rasterio's manylinux wheel (bundles GDAL but
# still links against host expat and OpenMP).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
        libgomp1 \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

# Install all dependencies first using a minimal stub so this large layer is
# cached when only source files change (only re-runs if pyproject.toml changes).
# [biweekly] adds Playwright — the UNICA bi-weekly fetch drives a JS-rendered
# listing page via headless Chromium (fetch_unica_biweekly.py --discover).
COPY pyproject.toml ./
RUN mkdir -p src/leviathan && touch src/leviathan/__init__.py && \
    pip install --no-cache-dir -e ".[batch,biweekly,pg]"

# Install the Chromium browser + its OS-level deps in a dedicated layer so it
# caches independently of source changes; chromium only, not every browser.
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*

# Copy real source after dependencies — only creates small new layers on change.
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/
# silver-gate config_check lint (node_silver_map) + DDL drift checks read sql/athena/ddl/*.sql at
# runtime -- the old images carried sql/ only via a pre-659a83ce layer; honest rebuilds dropped it
# (refire3 gate FAIL "DDL silver_psd.sql not found", 2026-07-24).
COPY sql/ ./sql/

# FENCE (incident I-1): stamp the image with what it was BUILT FROM. This RUN must come AFTER
# `COPY configs/` -- stamping earlier would fingerprint an empty directory and the manifest would
# lie. tests/unit/test_image_config_fence.py::test_dockerfiles_stamp_after_configs_copy pins that
# ordering. On 2026-07-24 this container could not say it was built from e0a33bf2, so a week was
# spent reading a config file that was correct.
RUN BUILD_GIT_COMMIT="$BUILD_GIT_COMMIT" BUILD_TIME="$BUILD_TIME" \
    python -m leviathan.common.image_stamp --write /app/IMAGE_MANIFEST.json

ENTRYPOINT ["python"]
