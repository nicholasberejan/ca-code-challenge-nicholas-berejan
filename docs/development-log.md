# AI Development Log

This document records meaningful observations from AI-assisted development
and resulting improvements to the development system. Routine prompting,
implementation steps, and accepted suggestions are intentionally omitted.

## Entries

### 2026-10-16: Planning-session decisions where AI output was changed or rejected

- **Top review.** The AI recommended "highest-rated review" because it was
  simple and deterministic. I rejected it as systematically favorable to
  brands and chose the review closest to the mean. My first tie rule
  ("closest without going over") was itself challenged during reconciliation:
  it could choose a review farther from the mean than an above-mean review.
  The final rule uses strict nearest distance, with the lower rating preferred
  only on exact ties.

- **Industry filter options.** The AI raised a question I had not considered:
  where the filter's available industries come from. Hard-coding them in
  React would duplicate backend state, while deriving them from a paginated
  brand response could produce an incomplete set. I chose a dedicated
  `GET /api/industries/` endpoint.

- **Industry filtering and aggregates.** During API design, I identified that
  joining Brand → Industry while also aggregating Brand → Review can multiply
  review rows when a brand matches more than one selected industry. Applying
  `distinct()` to the outer result would not necessarily repair aggregates
  already calculated over the multiplied rows. I chose to isolate industry
  membership in a subquery so the outer brand query can aggregate reviews
  independently. This became an explicit acceptance criterion: a brand
  matching multiple selected industries must appear once without inflated
  review count or average rating.

- **Average-rating authority.** Inspection of the source data showed that the
  stored WordPress ACF average disagrees with the average derived from Review
  ratings for four of five brands. Rather than treating the imported aggregate
  as authoritative, I chose Review rows as the source of truth and retained
  the WordPress value only as `legacy_average_rating` for source/audit
  purposes. This avoids maintaining two authoritative representations of the
  same value.

- **Average-rating precision.** The AI proposed rounding the API value to one
  decimal place. I moved presentation rounding to the UI and kept greater
  precision in the API contract so clients can observe a value consistent
  with the value used for sorting.

- **WordPress password migration.** The challenge permits resetting migrated
  passwords, which would have been the simpler implementation. Investigation
  showed that the source users use WordPress 6.8+ `$wp$` hashes. I chose to
  support those hashes as a transitional compatibility mechanism so existing
  credentials continue to work. On the first successful login, Django
  upgrades the stored password to its native configured hash. Because this
  introduces security-sensitive compatibility code, verification against
  known source credentials and explicit incorrect-password tests are required.

- **Authorization consistency.** I considered validating permissions against
  the auth service on every protected request, which would make role changes
  immediate but couple writes to auth-service availability. I instead chose
  short-lived, locally verified RS256 access tokens. This deliberately accepts
  a bounded role-staleness window of approximately five minutes in exchange
  for keeping token verification independent of auth-service availability.
  Refresh reloads the user's current roles from the auth database so stale
  roles do not propagate into newly issued access tokens.

- **Audit log.** The AI proposed an audit log on PATCH to mitigate the
  approximately five-minute role-staleness window. I removed it as scope with
  no `CHALLENGE.md` requirement behind it and accepted the bounded window
  explicitly instead. This was a useful check against allowing reasonable
  architectural ideas to become unnecessary assessment scope.

- **HTML sanitization.** The plan initially adopted the AI's recommendation
  to sanitize at render and keep stored HTML identical to WordPress. I
  reversed this after reconsidering the trust boundary: externally sourced
  WordPress HTML is sanitized once as it enters the new application. Future
  HTML write paths would need to pass through the same sanitizer before
  persistence.

- **Process.** Decision records had started to mention who suggested what.
  I moved that history here so `decisions.md` records only what was decided
  and why. `acceptance-criteria.md` records observable requirements, while
  this log records noteworthy aspects of the human/AI process that produced
  them.

### 2026-10-17: Transition from planning to implementation

- **Acceptance criteria before implementation.** Rather than allowing the
  implementation agent to determine what constitutes success while writing
  the application, I established and committed acceptance criteria before
  implementation. Architecture decisions were then reconciled against those
  criteria and `CHALLENGE.md`. This gives implementation agents an independent
  definition of expected behavior and reduces the risk of implementation and
  tests converging on the same incorrect assumption.

- **Incremental implementation strategy.** I chose not to ask the AI to
  implement the entire challenge from the completed architecture in one pass.
  Implementation will proceed in bounded, independently verifiable phases:
  project/tooling scaffolding, domain/import, API, SSR/SCSS, React, auth/shared
  library, and final integration. Each phase is planned before implementation
  and must satisfy its verification checkpoint before work proceeds.

- **Development-system improvements should be earned.** I am starting
  implementation without creating a large collection of speculative AI
  skills, agents, and hooks. Repeated failure patterns will determine what is
  promoted into persistent context, a reusable skill, a deterministic test,
  a hook, or another verification gate. The goal is for the development
  system to become stricter in response to observed failures rather than
  accumulating process for its own sake.
### 2026-10-17: Phase 1 (foundation) findings

- **A clean-clone test caught a silent packaging failure.** `uv build` writes
  a `.gitignore` containing `*` into its output directory, so the released
  shared-auth wheel in `wheels/` was invisible to git. Everything passed in
  the working copy; only rebuilding from a fresh copy of the tracked files
  exposed that the images could not build. Fixed with
  `--no-create-gitignore` in `scripts/lib-release.sh`. Lesson: verify from
  what git would actually ship, not from the working directory.
- **Gates were proven to fail, not just to pass.** Each new check (tsc,
  ESLint/jsx-a11y, Stylelint rules, ruff, the commit hook, the Claude Stop
  hook) was run against a deliberately planted violation before being
  trusted, so a silent or misconfigured check cannot report success.
- **Rules from `decisions.md` became lint rules.** The SCSS decisions
  (`@use` instead of `@import`, media queries only through the breakpoint
  mixin, nesting depth 2, BEM class names, no element selectors in
  components) are enforced by Stylelint rather than left to review.

### 2026-10-17: Independent reviewer subagent

- **Verification and review answer different questions.** Deterministic
  verification answers whether the known mechanical checks pass. An
  independent review answers whether the implementation appears to be the
  right implementation of the requirements, including whether the tests
  actually prove them. The implementing agent should not be the only judge
  of its own work.
- **Introduced after the foundations, not before.** The reviewer
  (`.claude/agents/reviewer.md`) was added only once the requirements,
  decisions and verification gates existed, so it reviews against settled
  sources rather than inventing its own standard.
- **Read-only and independent by design.** It reads `CHALLENGE.md`, the
  acceptance criteria and the decisions itself, inspects the actual diff,
  and does not rely on the implementing agent's summary. It reports findings
  by severity; the parent agent decides which are valid.
- **Enforcement deliberately deferred.** Invoking the reviewer is an
  instruction in `CLAUDE.md`, not a Stop-hook requirement. A hook will be
  added only if agents are observed skipping the review.

### 2026-10-17: Phase 2 (content import) findings

- **A security test caught the sanitizer library's permissive default.** The
  first sanitizer passed the approved tag/attribute allowlist to `nh3`, but
  `nh3` also allows `lang` and `title` on every tag unless told otherwise, so
  `<a href="…" title="…">` kept its `title`. The XSS/allowlist tests asserted
  the exact output rather than "no script tag", which is why it surfaced. The
  sanitizer now passes an empty `"*"` attribute set, and the payload list
  includes generic attributes.
- **The read-only guarantee was tested by removing it.** The test that the
  WordPress connection rejects writes was confirmed to pass only because of
  the read-only session setting: without it, the same statement is accepted.

### 2026-10-17: Phase 3 (public pages and API) findings

- **Rendering exposed a gap the import phase had missed.** Sanitizing body
  HTML at import (decisions §9) did not cover a plain-text field later
  rendered as a link: an ACF `website_url` of `javascript:…` would have been
  escaped but still clickable. Found while writing the brand template; the
  importer now keeps only `http(s)` URLs with a host. Lesson: the trust
  boundary covers every field that ends up in an attribute, not only the HTML
  bodies.
- **The independent reviewer caught two things passing tests could not.**
  The URL fix silently dropped rejected values, unlike every other anomaly
  the importer reports; and the README claimed brands without reviews sort
  last for every ordering, while the (correct) code and tests sort them first
  for ascending `review_count`. Both were fixed: rejected URLs are now
  reported, and the README matches the tested behaviour.
- **Key invariants were checked by breaking them.** Replacing the industry
  subquery with a plain join, or making top-review selection prefer
  below-mean ratings ("closest without going over"), each made the intended
  tests fail.

### 2026-10-18: Independent test auditor

- **Reviewing every generated test by hand does not scale,** and the agent
  that wrote an implementation should not be the only judge of the tests it
  wrote for it. A second read-only subagent, `test-auditor`, now audits the
  test evidence alongside the general `reviewer`.
- **It reasons from requirements to evidence.** It maps the acceptance
  criteria and decisions the change touches to the tests that actually
  exist, and asks of each regression test whether it would fail if the bug
  came back. Behavioral and acceptance-criteria coverage is the measure, not
  a line-coverage target.
- **It looks specifically for gamed tests:** weakened assertions, expected
  values changed to match output, deleted or skipped tests, mocking that
  bypasses the behavior under test, and verification that no longer runs the
  required tests.
- **Read-only, and humans still spot-check.** It recommends tests but never
  writes or edits them; high-risk tests can still get targeted human review.
  As with the reviewer, invoking it is an instruction in `CLAUDE.md`; a hook
  will be added only if agents are observed skipping it.

### 2026-10-18: Phase 4 (SCSS and BrandList) findings

- **Passing tests missed an accessibility requirement; the reviewer caught
  it.** The live region kept the old count while results refreshed, so a
  sort or page change that left the count unchanged was never announced.
  The only announcement test used a filter change that altered the count.
  The announcement is now emptied during each request and refilled when it
  completes, with a test for an unchanged count.
- **The test auditor found three criteria only partly proven:** abort was
  never asserted (the stale-response tests also pass with a request-ID
  guard and no abort), the Back test never crossed the filter change itself,
  and one-decimal rounding was only tested away from half-way values. That
  last gap hid a real inconsistency: the cards used `toFixed` (1.15 to 1.1)
  while the brand page rounded half up. Both now round the API's two-decimal
  value half up, tested at the boundaries on each side.
- **Mutation checks exposed a test-fixture blind spot.** The fake `fetch`
  ignored abort signals, so removing the "ignore failures from stale
  requests" guard broke nothing. A test for a stale request that fails after
  newer results arrived now covers it.
- **The reviewer also caught non-functional issues tests cannot:** an amber
  focus ring at about 2:1 contrast (now dark teal, white on the hero), and
  the review page depending on the brand page's partial (now a shared
  `content-panel` component).
- **Running the two review agents in parallel broke verification.** Each
  headless review session runs the project's Stop hook, so two sessions ran
  `scripts/verify.sh` at once and collided on the shared PostgreSQL test
  database; the test audit came back as a hook failure instead of a report.
  Run the agents one after the other (or tell them not to run `verify.sh`).

### 2026-10-18: Splitting `<BrandList />` further

- **I proposed extracting the loading message, the error and the results
  block into their own components.** I asked whether that was necessary
  and in line with CHALLENGE.md and React practice. The AI's assessment:
  CHALLENGE.md sets no internal structure, so it is a clarity question, not
  a requirement. The results block (busy wrapper, empty state, grid,
  pagination) and the error (an alert with Retry) each have a real contract
  worth naming. The one-line loading message does not, and extracting it
  would be splitting for symmetry.
- **Decision:** extract `BrandResults` and `LoadError`; keep the loading
  message inline; keep every "which state to show" decision in `BrandList`
  so children never learn about the URL or the API. Recorded in
  decisions §5.
- **The tests proved the refactor safe without changing.** Because the
  BrandList tests query roles, labels and text rather than component
  structure, all 38 frontend tests passed untouched after the extraction.
