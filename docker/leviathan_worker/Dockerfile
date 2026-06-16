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
COPY pyproject.toml ./
RUN mkdir -p src/leviathan && touch src/leviathan/__init__.py && \
    pip install --no-cache-dir -e ".[batch]"

# Copy real source after dependencies — only creates small new layers on change.
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

ENTRYPOINT ["python"]
