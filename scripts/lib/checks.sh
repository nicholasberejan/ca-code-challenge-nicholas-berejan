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

# Imports the seeded WordPress content into the web service's database, then
# re-imports with --expect-unchanged, which fails (and rolls back) if the
# second run would create, update or delete anything.
content_import_idempotency() {
  start_wordpress_db
  step "WordPress content import, then idempotent re-import (import_wordpress)"
  in_service_with_db web python manage.py import_wordpress
  in_service_with_db web python manage.py import_wordpress --expect-unchanged
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

# docs/decisions.md §12 requires both imports to be idempotent. The content
# import is checked by content_import_idempotency; the auth service's user
# import does not exist yet. Reported, never passed.
DEFERRED_CHECKS=(
  "Auth user import idempotency (import_wordpress_users run twice; second run must create/update nothing): user import not implemented yet"
)

report_deferred() {
  finish_step
  printf '\n==> Deferred checks (NOT run, NOT passed)\n'
  for check in "${DEFERRED_CHECKS[@]}"; do
    printf '    - %s\n' "$check"
  done
}
