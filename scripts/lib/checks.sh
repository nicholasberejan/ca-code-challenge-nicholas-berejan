# shellcheck shell=bash
# Verification checks, sourced by scripts/verify-fast.sh, scripts/verify.sh and
# scripts/test.sh. Each command is defined once, here. Every check runs inside
# a container; the host needs only Docker.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# VERIFY_QUIET=1 (set by .githooks/pre-commit): print one line per check and
# show a command's output only if it fails. Otherwise stream everything.
VERIFY_QUIET="${VERIFY_QUIET:-0}"
step_open=0

step() {
  if [ "$VERIFY_QUIET" = 1 ]; then
    finish_step
    printf '• %s ... ' "$*"
    step_open=1
  else
    printf '\n==> %s\n' "$*"
  fi
}

# Quiet mode: mark the current check as passed. Call before a final summary.
finish_step() {
  if [ "$step_open" = 1 ]; then
    printf '✓\n'
    step_open=0
  fi
}

run() {
  if [ "$VERIFY_QUIET" != 1 ]; then
    "$@"
    return
  fi
  local output status=0
  output="$(mktemp)"
  "$@" >"$output" 2>&1 || status=$?
  if [ "$status" -ne 0 ]; then
    printf '✗\n\n'
    cat "$output"
    step_open=0
  fi
  rm -f "$output"
  return "$status"
}

# Run a one-off command in a Compose service. --no-deps: the fast checks never
# start a database.
in_service() {
  run docker compose --profile tools run --rm --no-deps -T "$@"
}

# As above, but starts the service's database first (waiting for it to be
# healthy).
in_service_with_db() {
  run docker compose run --rm -T "$@"
}

build_images() {
  step "Build images (web image includes the production frontend build)"
  run docker compose --profile tools build --quiet web auth frontend shared-auth
}

# --- Python ------------------------------------------------------------------

python_lint() {
  for service in web auth; do
    step "ruff check + format check: services/$service"
    in_service "$service" ruff check .
    in_service "$service" ruff format --check .
  done
  step "ruff check + format check: packages/shared-auth"
  in_service shared-auth uv run --locked ruff check .
  in_service shared-auth uv run --locked ruff format --check .
}

shared_auth_types() {
  step "mypy --strict: packages/shared-auth"
  in_service shared-auth uv run --locked mypy
}

shared_auth_tests() {
  step "pytest: packages/shared-auth (installed as a wheel, no Django project)"
  in_service shared-auth uv run --locked pytest
}

django_checks() {
  for service in web auth; do
    step "Django system check + migration check: services/$service"
    in_service_with_db "$service" python manage.py check --fail-level WARNING
    in_service_with_db "$service" python manage.py makemigrations --check --dry-run
  done
}

# The WordPress source database (MariaDB `db` service): read by the web
# service's import tests and by the import idempotency check.
start_wordpress_db() {
  step "Start the WordPress source database"
  run docker compose up -d --wait db
}

django_tests() {
  start_wordpress_db
  for service in web auth; do
    step "pytest against PostgreSQL: services/$service"
    in_service_with_db "$service" pytest
  done
}

# Imports the seeded WordPress data into each service's database, then
# re-imports with --expect-unchanged, which fails (and rolls back) if the
# second run would create, update or delete anything.
import_idempotency() {
  start_wordpress_db
  step "WordPress content import, then idempotent re-import (import_wordpress)"
  in_service_with_db web python manage.py import_wordpress
  in_service_with_db web python manage.py import_wordpress --expect-unchanged
  step "WordPress user import, then idempotent re-import (import_wordpress_users)"
  in_service_with_db auth python manage.py import_wordpress_users
  in_service_with_db auth python manage.py import_wordpress_users --expect-unchanged
}

# The documented token flow against the running web and auth services,
# including an auth-service outage (scripts/e2e/auth_flow.py).
e2e_flow() {
  docker compose run --rm --no-deps -T -v "$REPO_ROOT/scripts/e2e:/e2e:ro" \
    -v "$E2E_STATE:/state" auth python /e2e/auth_flow.py "$1"
}

auth_flow_e2e() {
  step "End-to-end token flow: login, PATCH, 401/403, demotion, replay, logout"
  run docker compose up -d --wait db main-db auth-db
  run docker compose up -d web auth
  run wait_for_services
  E2E_STATE="$(mktemp -d)"
  trap 'e2e_flow cleanup >/dev/null 2>&1 || true; docker compose start auth >/dev/null 2>&1 || true; rm -rf "$E2E_STATE"' EXIT
  run e2e_flow main
  step "End-to-end: auth service stopped (public reads, PATCH with a valid token)"
  run docker compose stop auth
  run e2e_flow outage
  run docker compose start auth
  run wait_for_services
  step "End-to-end: edited description survives import_wordpress"
  run docker compose exec -T web python manage.py import_wordpress
  run e2e_flow verify
  run e2e_flow cleanup
  trap - EXIT
  rm -rf "$E2E_STATE"
}

wait_for_services() {
  for _ in $(seq 1 60); do
    if docker compose exec -T web python -c "import urllib.request as u; u.urlopen('http://localhost:8000/healthz'); u.urlopen('http://auth:8001/healthz')" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "web/auth did not become healthy" >&2
  return 1
}

# --- Frontend ----------------------------------------------------------------

frontend_static_checks() {
  step "tsc --noEmit"
  in_service frontend npm run --silent typecheck
  step "ESLint (with jsx-a11y)"
  in_service frontend npm run --silent lint
  step "Prettier check"
  in_service frontend npm run --silent format:check
  step "Stylelint"
  in_service frontend npm run --silent lint:styles
}

frontend_tests() {
  step "Vitest"
  in_service frontend npm run --silent test
}

frontend_build() {
  step "Vite production build (React bundle + SCSS)"
  in_service frontend npm run --silent build
}

# --- Deferred ----------------------------------------------------------------

# Checks required by the decisions whose feature does not exist yet are listed
# here and reported, never passed. Currently none.
DEFERRED_CHECKS=()

report_deferred() {
  finish_step
  if [ "${#DEFERRED_CHECKS[@]}" -eq 0 ]; then
    printf '\n==> Deferred checks: none\n'
    return
  fi
  printf '\n==> Deferred checks (NOT run, NOT passed)\n'
  for check in "${DEFERRED_CHECKS[@]}"; do
    printf '    - %s\n' "$check"
  done
}
