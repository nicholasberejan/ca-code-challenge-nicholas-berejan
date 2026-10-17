# syntax=docker/dockerfile:1
# Build context: repository root (see docker-compose.yml).
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /repo/services/auth
COPY wheels/ /repo/wheels/
COPY services/auth/pyproject.toml services/auth/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked
COPY services/auth/ ./

EXPOSE 8001
CMD ["sh", "-c", "python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8001"]
