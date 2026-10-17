#!/usr/bin/env bash
# Full verification: everything in verify-fast.sh, plus checks that need
# PostgreSQL and the production frontend build. The authoritative "done" gate.
source "$(dirname "$0")/lib/checks.sh"

build_images
python_lint
shared_auth_types
shared_auth_tests
frontend_static_checks
frontend_tests
django_checks
django_tests
content_import_idempotency
frontend_build
report_deferred

finish_step
printf '\nFull verification passed (%d check(s) deferred, listed above).\n' \
  "${#DEFERRED_CHECKS[@]}"
