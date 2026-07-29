# PRICE_AND_PLAYBOOKS W1c -- the BROWSER image: the three challenged venues' fetch producers.
#
# WHY A SECOND IMAGE AND NOT THE WORKER
# -------------------------------------
# leviathan_worker already installs [batch,biweekly,pg] and runs `playwright install chromium`, so
# it COULD run these producers. It should not: that image is the one every silver task, gate and
# Glue-adjacent job runs on, its rebuilds are already load-bearing (SILVER-F085), and a leg whose
# whole purpose is to satisfy a bot check must be able to move its browser version WITHOUT
# re-qualifying the entire silver estate. Splitting them means the WAF-facing dependency has its own
# blast radius -- and its own pin, in requirements.txt beside this file.
#
# ENTRYPOINT CONVENTION -- DO NOT CHANGE
# --------------------------------------
# `ENTRYPOINT ["python"]`, verbatim from leviathan_worker. The Batch job definitions pass their
# command as ["-c", "<code>"] (and the DAG descriptors as ["jobs/ingest/fetch_x.py", "--mode", ...])
# on the assumption that the entrypoint already prepends the interpreter. An image that "helpfully"
# set ENTRYPOINT ["python", "jobs/..."] or CMD would break every jobdef that targets it.
FROM python:3.11-slim

WORKDIR /app

# ---------------------------------------------------------------------------
# 1. The leviathan core dependency layer, cached against pyproject.toml alone (the worker's stub
#    trick: install the package with an empty src/ so this large layer does not re-run on a source
#    change).
#
#    NOTE the extras that are deliberately ABSENT. This image runs jobs/ingest/fetch_{dce,euronext,
#    bursa}*.py and nothing else, and those need boto3 / pandas / openpyxl / requests -- all CORE
#    dependencies. [batch] would add rasterio, pdfplumber, pypdf, yfinance and databento; [training]
#    and [embed] would add multi-hundred-MB wheels. None of it is imported on this path, and every
#    megabyte here is a cold-start second on Fargate.
# ---------------------------------------------------------------------------
COPY pyproject.toml ./
RUN mkdir -p src/leviathan && touch src/leviathan/__init__.py && \
    pip install --no-cache-dir -e "."

# ---------------------------------------------------------------------------
# 2. Playwright, PINNED (see requirements.txt for why the pin is evidence and not taste), then the
#    Chromium build + its OS-level libraries. Two separate layers from the source copy below, so a
#    code change never re-downloads a ~150 MB browser.
#
#    --with-deps is what installs the ~40 shared libraries (libnss3, libatk, libxkbcommon, ...) that
#    a headless Chromium needs on a slim base and that are NOT in python:3.11-slim. Without it the
#    browser installs and then fails to LAUNCH, which is a runtime failure on Fargate rather than a
#    build failure here.
# ---------------------------------------------------------------------------
#    PLAYWRIGHT_BROWSERS_PATH is set BEFORE the install and kept for the runtime, and that ordering
#    is load-bearing: the default install location is $HOME/.cache/ms-playwright, so a browser
#    downloaded as root under one HOME is invisible to a process running under another. An absolute,
#    HOME-independent path removes the whole class ("Executable doesn't exist at ...", at launch, on
#    Fargate, from an image that built clean).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY docker/leviathan_browser/requirements.txt ./browser-requirements.txt
RUN pip install --no-cache-dir -r browser-requirements.txt
RUN playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 3. The real source, last -- only small layers change on a code push.
#    configs/ and sql/ ride along for the same reason the worker carries them: they are read at
#    RUNTIME (the silver registry / the node_silver_map + DDL-drift lints), old images had them only
#    through stale cached layers, and the first honest rebuild without them broke three scheduled
#    fires on 2026-07-24. This image is not supposed to run those steps -- but "not supposed to" is
#    exactly what that incident was made of, and the trees are kilobytes.
# ---------------------------------------------------------------------------
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/
COPY sql/ ./sql/

# The producers import leviathan.* from the editable install above; PYTHONPATH is belt-and-braces
# for a `python jobs/ingest/...` invocation whose sys.path[0] is jobs/ingest/.
ENV PYTHONPATH=/app/src
# Unbuffered so a challenge-failure log line reaches CloudWatch before the process exits 7.
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python"]
