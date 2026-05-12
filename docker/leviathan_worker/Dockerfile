FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
COPY jobs/ ./jobs/
COPY configs/ ./configs/

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["python"]
