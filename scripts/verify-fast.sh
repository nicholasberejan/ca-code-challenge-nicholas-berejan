#!/usr/bin/env bash
# Fast verification: lint, format, types and unit tests. No databases.
# Runs on every commit (.githooks/pre-commit).
source "$(dirname "$0")/lib/checks.sh"

build_images
python_lint
shared_auth_types
shared_auth_tests
frontend_static_checks
frontend_tests

finish_step
printf '\nFast verification passed.\n'
