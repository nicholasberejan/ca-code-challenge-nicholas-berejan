#!/usr/bin/env bash
# Build the shared-auth wheel for the version in its pyproject.toml into the
# local wheelhouse (wheels/). Released versions are immutable: to release a
# change, bump the version first.
set -euo pipefail
cd "$(dirname "$0")/.."

run() {
  docker compose --profile tools run --rm --no-deps -T shared-auth "$@"
}

version="$(run python -c \
  'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
wheel="wheels/shared_auth-${version}-py3-none-any.whl"

if [ -e "$wheel" ]; then
  echo "error: $wheel already exists. Released versions are immutable;" \
    "bump the version in packages/shared-auth/pyproject.toml first." >&2
  exit 1
fi

# --no-create-gitignore: uv otherwise writes a `*` .gitignore into wheels/,
# which would stop released wheels from being committed.
run uv build --wheel --no-create-gitignore --out-dir /repo/wheels
echo "Released $wheel"
echo "To upgrade a service: set shared-auth==${version} in its pyproject.toml," \
  "then run 'make lock'."
