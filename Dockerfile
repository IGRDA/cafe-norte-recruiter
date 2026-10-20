# One image: Python application, static browser assets, fixed knowledge base and its index.
# Cloud Run runs it with CPU always allocated so Pipecat voice tasks keep running after the
# session-start HTTP response returns.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/
WORKDIR /app

# Dependencies first, so source edits do not invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --all-extras --no-install-project

COPY src ./src
COPY web ./web
COPY config ./config
COPY kb ./kb
COPY scripts/build_index.py ./scripts/build_index.py
RUN uv sync --locked --no-dev --all-extras
# Precompute the versioned retrieval index into the image. Enabled once knowledge/index.py lands.
# RUN uv run python scripts/build_index.py

ENV PORT=8080
EXPOSE 8080
CMD ["uv", "run", "--no-sync", "uvicorn", "cafe_norte.main:create_default_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
