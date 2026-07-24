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

ENTRYPOINT ["python"]
