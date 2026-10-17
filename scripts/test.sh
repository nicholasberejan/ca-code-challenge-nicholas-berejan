#!/usr/bin/env bash
# Run every test suite: shared library, frontend, and both Django services.
source "$(dirname "$0")/lib/checks.sh"

build_images
shared_auth_tests
frontend_tests
django_tests

finish_step
printf '\nAll test suites passed.\n'
