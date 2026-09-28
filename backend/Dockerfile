# StEP1 backend — same image for local compose and App Runner.
#
# Build:  docker build -t step1-backend .
# Run:    docker compose up --build   (API + local Postgres)

FROM python:3.12-slim

# Never write .pyc, never buffer stdout (JSON logs must stream to CloudWatch).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Dependencies first so code edits don't bust the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only what the service needs at runtime. .env is excluded by .dockerignore —
# a security boundary, not an optimization: secrets reach prod via the
# service config / Secrets Manager, never an image layer.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Non-root: nothing here needs root, and App Runner / CIS both expect it.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /srv/data/uploads \
    && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000

# slim has no curl; probe /health with the stdlib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# Migrations run before uvicorn (entrypoint.sh), so first boot against an
# empty database creates the schema instead of 503ing every DB route.
ENTRYPOINT ["./entrypoint.sh"]
