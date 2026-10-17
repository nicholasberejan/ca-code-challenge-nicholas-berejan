# Project Instructions

## Sources of Truth

- `CHALLENGE.md` is the authoritative product specification.
- WordPress CPT and ACF definitions are authoritative for source schema.
- `reference/theme.css` is the reference stylesheet.
- `docs/acceptance-criteria.md` contains approved behavioral criteria.

Do not modify source-of-truth files unless explicitly instructed.

## Engineering Priorities

1. Correctness
2. Simplicity
3. Clear service/domain boundaries
4. Maintainability
5. Testability
6. Accessibility

Avoid unnecessary abstractions, dependencies, and infrastructure.

## Architecture

This repository contains four distinct concerns:

- Main Django application — migrated content, public pages, brand API.
- React frontend — interactive BrandList.
- Auth Django service — authentication, users, roles and permissions.
- Shared Python package — only genuinely shared authentication/
  authorization functionality.

Do not move responsibilities across these boundaries without discussing
the architectural reason first.

## Django

- Keep business/domain logic out of views where practical.
- Use explicit relational modeling rather than reproducing WordPress's
  post/postmeta structure.
- Avoid unnecessary signals and model overrides.
- Database operations that require atomicity should use transactions.
- Migration/import behavior must remain idempotent.

## React

- Use TypeScript if supported by the existing frontend setup.
- Prefer small components with clear responsibilities.
- Handle loading, error, empty, and populated states explicitly.
- Maintain semantic HTML and keyboard accessibility.
- Avoid duplicating backend business rules in the frontend.

## SCSS

- Use design tokens for repeated visual primitives.
- Separate global/foundation styles from component styles.
- Avoid unnecessary nesting and excessive selector specificity.
- Component styles should have clear ownership.

## Testing

Tests are evidence of requirements being satisfied; they do not define
the requirements.

Do not:
- weaken assertions to make implementations pass
- skip failing tests without justification
- modify acceptance criteria to match an implementation
- suppress lint/type errors merely to make checks pass
- excessively mock behavior under test

If an existing test appears incorrect, explain why before modifying it.

## Workflow

Before implementation:
1. Read the relevant requirements and source files.
2. Inspect the existing code.
3. Identify affected components.
4. Propose an approach.
5. Surface important ambiguities.

During implementation:
- Make focused changes.
- Verify incrementally.
- Avoid unrelated refactoring.

Before completion:
- Run relevant tests.
- Run lint/type checks.
- Verify against acceptance criteria.
- Report assumptions and unresolved risks.

## Agent Corrections

When corrected, determine whether the correction represents:
- project knowledge → update `CLAUDE.md`
- reusable procedure → create/update a skill
- deterministic requirement → automate via test/hook/CI
- one-off task context → do not persist unnecessarily

## Verification

`scripts/verify-fast.sh` and `scripts/verify.sh` are the canonical fast
and full verification entry points. Every check is defined once, in
`scripts/lib/checks.sh`, and runs inside Docker containers.

- `verify-fast.sh`: lint, format, types and unit tests; no databases.
  Runs on every `git commit` via `.githooks/pre-commit`
  (enabled per clone with `make hooks`).
- `verify.sh`: everything in fast, plus Django tests on PostgreSQL,
  Django checks, migration checks and the production frontend build.
  The Claude Code Stop hook (`scripts/claude-stop-verify.sh`) runs it
  before a turn ends whenever non-Markdown files changed.

Checks whose feature does not exist yet are listed as deferred in
`scripts/lib/checks.sh` and reported, never counted as passed. When a
feature lands, replace its deferred entry with a real check.

Do not weaken, skip or bypass a check (including `--no-verify`) to get a
passing result.
