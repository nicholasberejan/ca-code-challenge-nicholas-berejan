# syntax=docker/dockerfile:1
# Build context: repository root (see docker-compose.yml).

# --- Frontend dependencies. Also used by the `frontend` tools service. ---
FROM node:24-slim AS frontend-deps
WORKDIR /repo/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

# --- Frontend production build: React bundle and compiled SCSS. ---
FROM frontend-deps AS frontend-build
COPY frontend/ ./
RUN npm run build

# --- Django web service. ---
FROM python:3.12-slim-bookworm AS web
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# mysqlclient (read-only WordPress source connection) builds from source
# against the MariaDB client library.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc pkg-config libmariadb-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo/services/web
COPY wheels/ /repo/wheels/
COPY services/web/pyproject.toml services/web/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY services/web/ ./

# Outside the bind-mounted source tree, so a dev bind mount never hides it.
COPY --from=frontend-build /repo/frontend/dist /opt/frontend-dist

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]
