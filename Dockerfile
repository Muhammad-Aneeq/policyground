# API image for docker-compose. Not used by the default developer loop.
FROM python:3.12-slim

# uv, matching the local toolchain — a different resolver in the container would mean the image
# could work while a clean local install did not.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first, so a corpus or code edit does not re-resolve the environment.
COPY pyproject.toml uv.lock README.md ./
COPY backend/src/policyground/__init__.py backend/src/policyground/
RUN uv sync --frozen --no-dev --extra postgres

COPY backend/ backend/
COPY corpus/ corpus/
COPY evals/ evals/

ENV PATH="/app/.venv/bin:$PATH" \
    APP_MODE=local \
    PYTHONUNBUFFERED=1

# The index is built at start rather than baked in: it must match the mounted corpus, and a stale
# baked-in index would answer from policies the container is not actually serving.
CMD ["sh", "-c", "pg ingest --rebuild && pg serve --host 0.0.0.0 --port 8000"]
