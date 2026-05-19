FROM python:3.11-slim

WORKDIR /app

# System libraries required by rasterio's manylinux wheel (bundles GDAL but
# still links against host expat and OpenMP).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libexpat1 \
        libgomp1 \
        libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

RUN pip install --no-cache-dir -e ".[batch]"

# Install Playwright's headless Chromium for JS-rendered scraping jobs.
# playwright install-deps resolves system library dependencies (libnss3, libgbm1, etc.).
RUN playwright install chromium && playwright install-deps chromium

ENTRYPOINT ["python"]
