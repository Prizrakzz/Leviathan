FROM python:3.11-slim

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

# FENCE (incident I-1): build provenance. .dockerignore excludes .git, so NO image can ever run
# `git rev-parse` on itself (this is exactly why jobs/batch/pattern_records_sweep_task.py:219-225
# falls back to "unknown"). The commit MUST be injected as a build ARG by the build script.
#
# CACHE FENCE (2026-08-04): these two ARGs are declared HERE, immediately above their ONLY
# consumer, and must never be hoisted back to the top of the file. Docker scopes an ARG to every
# instruction that FOLLOWS it and treats a following RUN as though the arg were in that command's
# environment -- so the RUN's cache key moves whenever the arg's value moves, even when the
# command never mentions the name. BUILD_GIT_COMMIT is a NEW VALUE ON EVERY COMMIT. Declared at
# the top, it therefore invalidated the pip-install layer (863 MB) and the `playwright install`
# layer (1.03 GB) on every single build, and every push then had to move ~2 GB through the Docker
# Desktop proxy that breaks the pipe on GB PUTs. Below those layers, their cache keys depend only
# on their real inputs: the base image, the apt set, pyproject.toml and the playwright version.
# This paragraph is NOT the fence -- the fence is
# tests/unit/test_image_config_fence.py::test_provenance_args_stay_below_the_heavy_layers, which
# fails if either ARG is moved above the pip or `playwright install` RUN.
ARG BUILD_GIT_COMMIT=unknown
ARG BUILD_TIME=unknown

# Stamp the image with what it was BUILT FROM. This RUN must come AFTER
# `COPY configs/` -- stamping earlier would fingerprint an empty directory and the manifest would
# lie. tests/unit/test_image_config_fence.py::test_dockerfiles_stamp_after_configs_copy pins that
# ordering. On 2026-07-24 this container could not say it was built from e0a33bf2, so a week was
# spent reading a config file that was correct.
RUN BUILD_GIT_COMMIT="$BUILD_GIT_COMMIT" BUILD_TIME="$BUILD_TIME" \
    python -m leviathan.common.image_stamp --write /app/IMAGE_MANIFEST.json

ENTRYPOINT ["python"]
