#!/usr/bin/env bash
# Re-resolve a service's uv.lock after changing its pyproject.toml (for example
# a new shared-auth pin). Usage: scripts/lock.sh [web|auth ...]
set -euo pipefail
cd "$(dirname "$0")/.."

services=("$@")
if [ ${#services[@]} -eq 0 ]; then
  services=(web auth)
fi

for service in "${services[@]}"; do
  echo "==> uv lock: services/$service"
  docker compose run --rm --no-deps -T \
    -v "$PWD/wheels:/repo/wheels:ro" \
    "$service" uv lock
done
echo "Rebuild the images to install the new lockfiles: docker compose build"
