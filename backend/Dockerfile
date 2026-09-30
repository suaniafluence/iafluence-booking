# Build stage: install runtime dependencies only (no pytest/httpx) into /app/.venv.
FROM python:3.12-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Runtime stage: no uv, no build cache.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
# Fonts for the session report infographics (SVG rendered to PNG by resvg).
RUN apt-get update \
 && apt-get install --yes --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home app && mkdir /app && chown app /app

WORKDIR /app
COPY --from=build --chown=app /app/.venv ./.venv
COPY --chown=app alembic.ini ./
COPY --chown=app alembic ./alembic
COPY --chown=app app ./app
COPY --chown=app scripts ./scripts
USER app

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
