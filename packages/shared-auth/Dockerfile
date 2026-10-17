# Tooling image for the shared-auth package: runs its checks and builds its
# wheel. The package source is bind-mounted at run time (see docker-compose.yml).
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_NO_EDITABLE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /repo/packages/shared-auth
