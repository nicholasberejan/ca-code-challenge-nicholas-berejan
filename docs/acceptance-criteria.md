# Acceptance Criteria

These criteria define the externally observable behavior required by
`CHALLENGE.md`.

`CHALLENGE.md` remains the authoritative product specification.

Criteria that depend on unresolved architectural decisions are explicitly
marked **TBD** and must be resolved before implementation of the affected
feature begins.

## 1. Django Backend

### Domain Model

- Brands, reviews, industries, and reviewer identity are represented using
  a relational domain model rather than reproducing WordPress's
  `wp_posts` / `wp_postmeta` structure.
- WordPress slugs are preserved for migrated brands and reviews.
- The relationship between reviews and brands is preserved.
- Industry relationships are preserved.
- Reviewer identity from the source data is preserved in an appropriate
  form.
- Every imported brand, review, reviewer and industry records its WordPress
  ID as a unique source identity, separate from its Django primary key and
  from its slug.
- A brand can belong to more than one industry (many-to-many), even though
  every seeded brand has exactly one.
- Each WordPress user who authored a review becomes a `Reviewer` (WordPress
  user ID, display name) owned by the main app. Users who authored no
  reviews are not imported into the main app.
- A review's byline is its reviewer's display name. The WordPress
  `reviewer_name` field is not stored.
- `reviewer_location` is stored on the review, not the reviewer.
- The main app stores no user accounts, passwords, roles or permissions and
  has no Django admin. Brand edits happen only through the protected
  update endpoint.
- Yoast SEO fields are not migrated. A brand page's `<title>` comes from the
  brand name and its `<meta name="description">` from its
  `short_description`.

### Data Migration

- WordPress brands are migrated into the Django application.
- WordPress reviews are migrated and associated with the correct brands.
- WordPress industry relationships are migrated.
- Reviewer identity is preserved.
- Running the migration multiple times does not create duplicate records.
- Re-running the migration produces deterministic results for
  source-controlled data.
- Re-running the import against unchanged source data creates and updates
  nothing.
- Imported rows are matched to their source by WordPress ID, not slug. If a
  WordPress slug changes, the next run updates the existing Django entity's
  slug; no duplicate entity is created, and the old URL is not redirected.
- Split fields by owner. WordPress owns title, content, slug, ACF fields,
  industries, and reviews; they are overwritten on each import. Django owns
  `short_description`: import sets it only when it creates a brand and never
  overwrites it after that, so an edit made through the PATCH endpoint
  survives re-import.
- A brand's industries are replaced to match the source on every run.
- The import reads the WordPress MariaDB database directly. The main app's
  `import_wordpress` imports industries, brands, reviewers and reviews; the
  auth service's `import_wordpress_users` imports users, password hashes and
  roles. The two commands are independent and can run in either order.
- Each import runs in a single transaction: a failure leaves no partially
  imported data.
- Only published WordPress content is migrated.
- Dates are taken from `post_date_gmt` and stored in UTC.
- A review whose brand is not in the imported source is skipped and
  reported.
- The import prints a summary of created, updated, unchanged and missing
  records, and reports any review whose `reviewer_name` differs from its
  author's display name.
- The import never writes to the WordPress database.
- The import reports any brand or review postmeta key that is neither
  mapped to a field nor explicitly dropped, with the number of posts
  carrying it. Unrecognised keys never cause the import to fail.

### Missing Source Entities and Pruning

- By default, brands, reviews, industries and reviewers that exist in Django
  but are missing from WordPress are reported after import and not deleted.
- With an explicit `--prune` flag, within the same transaction as the
  import:
  - a review missing from the source is deleted;
  - a brand missing from the source is deleted together with its reviews;
  - an industry missing from the source is deleted and no longer offered as
    a filter option;
  - a reviewer left with no reviews is deleted.
- Without `--prune`, reviewers left with no reviews are reported.
- The auth service's user import never deletes users; users missing from
  the source are reported.

### Server-Rendered Pages

- `/` renders a homepage containing a hero and recent reviews.
- `/brand/<slug>/` renders the corresponding migrated brand.
- `/review/<slug>/` renders the corresponding migrated review.
- Brand and review URLs preserve the WordPress slugs.
- Requests for nonexistent brand or review slugs return an appropriate
  404 response.
- Recent-review ordering is deterministic.
- The homepage shows a hero and the 6 most recent reviews, newest first
  (ties broken by WordPress ID).
- A brand page shows the brand's name, industry badges, derived average
  rating (one decimal place) and review count, website, founded year,
  headquarters, body, and all of its reviews, newest first.
- A review page shows a link back to its brand, its title, rating, reviewer
  display name and location, publish date, and body.
- `/brand/` hosts the `<BrandList />` component.
- WordPress static pages (Home, About, Contact) are not migrated, and the
  site navigation does not link to them.

### HTML Sanitization

- Brand and review body HTML is sanitized during import, before it is
  stored, by a single sanitizer that is tested against representative XSS
  payloads.
- Stored and rendered body HTML contains only allowlisted tags (`p`, `br`,
  `strong`, `em`, `a`, `ul`, `ol`, `li`, `blockquote`, `h2`–`h4`); the only
  allowed attribute is `href` on links.
- `<script>`, event-handler attributes and `style` never appear in stored or
  rendered body HTML.
- Links may only use `http`, `https` or `mailto`; `javascript:` links are
  removed.
- No unsanitized external HTML is ever marked safe. All other text fields,
  including `short_description`, are escaped when rendered.

## 2. Brand REST API

### Listing

`GET /api/brands/`:

- is publicly accessible.
- returns paginated brand results.
- supports filtering by industry.
- supports sorting by average rating.
- supports sorting by review count.
- returns sufficient information for each brand card:
  - name
  - slug
  - industries, as `industries: [{slug, name}]`
  - average rating
  - review count
  - short description
  - top review snippet

### Average Rating

- Average rating is derived from the brand's review ratings and calculated
  per request; a stored copy can be added later if scale requires it.
- `average_rating` is a JSON number rounded to two decimal places (e.g.
  `3.92`), or `null` for a brand with no reviews.
- Sorting by average rating uses the unrounded derived value. Brands with no
  reviews sort last in either direction. Ties are broken by slug.
- The WordPress `average_rating` value is retained as
  `legacy_average_rating` for source/audit reference only. It is not
  returned by the API and is not used for display, sorting or any other API
  behavior.

### Short Description

- `short_description` is seeded from `post_excerpt` in the WordPress data
  when present; otherwise from ~22 words of `post_content` with tags
  stripped and entities decoded.
- A seeded value is stored as-is even if it exceeds the 300-character limit
  that applies to PATCH edits.

### Top Review

- The top review is the review whose rating is closest to the brand's
  derived average rating (smallest absolute distance).
- Only when two reviews are equally distant from the average is the lower
  rating preferred. Examples:
  - average 3.6, candidate ratings 3 and 4: the 4 is selected (it is
    closer).
  - average 3.5, candidate ratings 3 and 4: the 3 is selected (equally
    distant; lower wins).
- Remaining ties are broken by the most recent review, then by WordPress
  post ID.
- Equal distances are recognised exactly; selection is not affected by
  floating-point rounding.
- The snippet includes review slug, title, rating, reviewer name, and
  roughly the first 160 characters of plain-text body.
- A brand with no reviews returns `null`.

### Filter, Sort, Pagination and Errors

- Filter: `industry=<slug>`, repeatable. Brands in any of the given
  industries are returned. An unknown slug returns 400.
- Sort: `ordering=average_rating|-average_rating|review_count|-review_count`.
  Default is `-average_rating`, with slug as the tie-break.
- Pagination: `page` and `page_size` (default 12, maximum 50). The envelope
  is `{count, next, previous, results}`.
- Errors: an invalid parameter returns 400 with
  `{"errors": {"<param>": ["..."]}}`. An out-of-range page returns 404.
- Filtering by several industries never duplicates a brand or inflates its
  aggregates. Example: a brand belonging to both Industry A and Industry B,
  with 12 reviews, requested with `industry=a&industry=b`, appears exactly
  once, with `review_count` 12 (not 24) and `average_rating` equal to the
  actual average of its 12 reviews.

### Industries

`GET /api/industries/`:

- is publicly accessible.
- returns every industry (slug and name), independent of which brands are
  on the current page or match the current filter.

### Protected Brand Update

`PATCH /api/brands/<slug>/`, a write endpoint for editing a brand's short
description:

- requires authentication.
- rejects invalid or missing authentication with 401.
- rejects an authenticated user without editor permission with 403.
- allows a user with editor permission to update the short description.
- does not permit modification of fields outside the endpoint's intended
  scope.
- on success, returns 200 with the updated brand in the same shape as a
  listing row.
- validates `short_description`:
  - must be a non-empty string;
  - maximum length 300 characters (after trimming);
  - surrounding whitespace trimmed;
  - HTML treated as text.
- leaves public GET endpoints and server-rendered pages accessible without
  authentication.

## 3. React BrandList

`<BrandList />`:

- consumes the brand listing API rather than embedding brand data.
- provides an industry filter.
- provides a sort control.
- handles loading state.
- handles empty-result state.
- handles API/error state.
- renders brand information returned by the API.
- shows one industry badge per industry on each card, sorted by name.
- displays each brand's average rating formatted to one decimal place.
- populates the industry filter from `GET /api/industries/`.
- supports keyboard interaction for interactive controls.
- uses appropriate semantic HTML.
- meets basic accessibility expectations.
- is usable on mobile and desktop viewport sizes.
- keeps filter, sort and page in the URL as the single source of truth for
  the user's choices; fetched data is held by small custom hooks with no
  global store, context provider, or data-fetching library.
- never shows results from an older request after a newer one has been made
  (in-flight requests are aborted when parameters change).
- includes a single-select `<select>` element with an "All industries"
  option. The API still accepts repeated values for future expansion to
  multi-select.
- Loading, empty and error UX:
  - On first load, a loading message is shown. On later changes, the
    previous results stay visible but dimmed, and the results region is
    marked `aria-busy="true"` until the new results arrive.
  - After each load, the number of brands is announced through a polite
    live region.
  - An empty result shows a "No brands match" message with a control that
    clears the filter.
  - A failed request shows an error message with a Retry control that
    repeats the last request; the filter and sort controls remain usable.
- Pagination interaction:
  - Previous and Next buttons with a "Page X of Y" label; a button is disabled
    (not hidden) when there is no page in that direction.
  - After a page change, keyboard focus moves to the results heading.
  - Changing the filter or sort resets to page 1.
- URL synchronization behavior:
  - Filter, sort and page live in the query string with the same names as the API, and default values are omitted.
  - User changes pushState a new history entry; popstate re-reads the URL.
  - Invalid URL values fall back to defaults instead of erroring.
  - Observable: a deep link reproduces the view, and Back restores the previous filter.

## 4. SCSS

- SCSS source is maintained in an organized source tree.
- SCSS compiles successfully into CSS.
- The resulting styling is structurally equivalent to the supplied
  WordPress theme; byte-for-byte output is not required.
- Repeated design values are represented using an intentional token
  strategy.
- Global/foundation, layout, and component concerns have clear ownership.
- Styles are structured so a new component can be added without requiring
  modification of unrelated component styles.
- Responsive behavior from the source theme is preserved or intentionally
  improved.
- Compilation instructions are documented in README.
- SCSS lives under `frontend/scss/`, organized into `abstracts/`, `base/`,
  `layout/`, `components/` and `pages/` partials with a single `main.scss`
  entry point, using `@use`/`@forward` (not `@import`).
- Design tokens are defined once in an SCSS token map and emitted as CSS
  custom properties.
- Component styles use single-class BEM-style selectors (e.g.
  `.card__title`) rather than descendant element selectors, with nesting at
  most two levels deep and media queries via a shared breakpoint mixin.
- The React component uses the same SCSS classes as the server-rendered
  pages; there is no second styling system.

## 5. Authentication and Authorization Service

### Service Boundary

- Authentication and authorization run in a separate Django service.
- The auth service has its own database.
- Each service has its own PostgreSQL database in its own container
  (`main-db`, `auth-db`). Tests run against PostgreSQL.
- The main application does not store passwords.
- The main application does not own user roles or permissions.
- The main application never sees passwords or refresh tokens.

### User Migration

- WordPress users exist in the auth service after migration.
- Re-running user migration does not create duplicate users.
- Re-running user migration never modifies an existing user: a role
  changed in the auth service, a deactivation, and an upgraded password
  hash all survive re-import.
- Migrated users log in with their WordPress login name as `username`.
- WordPress administrators can sign in to the auth service's Django admin.
- The chosen password migration/reset behavior is documented.
- Migrated users can log in with their existing WordPress passwords (the
  `$wp$` format present in the source data); an incorrect password is
  rejected.
- After a user's first successful login, their stored password hash is
  upgraded to Django's native hasher, and later logins with the same
  password still succeed.
- Tests cover these behaviors using known source credentials.

### Authentication

- Valid credentials can be exchanged for a token.
- Invalid credentials are rejected.
- Inactive users cannot log in.
- Access tokens are RS256-signed JWTs that expire after 5 minutes, carrying
  `sub`, `roles`, `iss`, `aud`, `exp`, `iat` and `jti`.
- Only the auth service holds the signing (private) key. The main app
  verifies signature, expiry, issuer and audience locally with the public
  key, without calling the auth service.
- Refresh tokens last about one day and are rotated on every use; a used or
  revoked refresh token is rejected.
- `POST /api/token/` exchanges `username` and `password` for an access token
  and a refresh token.
- `POST /api/token/refresh/` exchanges a refresh token for a new access token
  and a new refresh token.
- `POST /api/token/logout/` revokes the given refresh token; it can no longer
  be used.

### Authorization

- At least `reader` and `editor` roles exist.
- The auth service is authoritative for role/permission assignments.
- Roles are changed, users deactivated, and a user's sessions revoked
  through the auth service's Django admin. Revoking a user's sessions
  rejects all of their existing refresh tokens.
- An editor can call the protected brand-update endpoint.
- A reader cannot call the protected brand-update endpoint.
- WordPress-role-to-application-role mapping: "administrator" becomes "editor", "subscriber" becomes "reader".
  Unknown roles map to "reader". Only "editor" role can PATCH.
- Role changes and deactivation take effect at refresh: every refresh
  reloads the user from the auth database, refuses inactive users, and
  builds the new access token's roles from the user's current roles (never
  copied from the old token).
- An already-issued access token keeps its roles until it expires, so a
  demoted or deactivated user can act for at most one access-token lifetime
  (about 5 minutes). This is an accepted, documented tradeoff. Observable:
  log in as an editor, demote the user, refresh; the new access token has no
  editor role and PATCH returns 403.
- When the auth service is unavailable, public GET endpoints and
  server-rendered pages are unaffected. PATCH with a valid, unexpired token
  still succeeds. Login and refresh fail.
- The main app receives the auth service's public key through
  configuration (an environment variable) and never fetches it from the
  auth service at runtime. If the key is missing, the main app fails at startup with a
  clear configuration error.

## 6. Shared Python Library

- Shared code is implemented as a separate installable Python package.
- The package has its own `pyproject.toml`.
- Both Django services install a defined version of the package.
- The package contains only cross-service contracts and the authentication
  infrastructure CHALLENGE.md requires there; each module's place in it is
  justified in the documentation.
- Shared authentication/token functionality required by the main
  application is provided through the package.
- Shared permission-checking functionality required by the main
  application is provided through the package.
- The package has tests that run independently of either Django project.
- Package installation/versioning and upgrade behavior are documented.
- The package defines the token contract (claim names, issuer/audience,
  signing algorithm) and role/permission names in one place; the auth
  service issues tokens and the main app verifies them using these same
  definitions.
- The core (claims, permissions, token verification) has no Django
  dependency. DRF authentication and permission classes are an optional
  part of the package.
- The auth service installs only the core; the main app installs the core
  plus the DRF classes. Token signing stays in the auth service.
- Core tests run with pytest alone; the DRF classes are tested with a
  minimal Django configuration inside the package's test suite, not either
  service's project.
- Each release builds a versioned wheel into a local wheelhouse
  (`wheels/`). Each service pins an exact library version and installs it
  from the wheelhouse, so one service can upgrade without the other.
- README documents the expand-then-contract process for a breaking change:
  the verifier (main app) upgrades to a version accepting both formats
  before the issuer (auth service) starts emitting the new one.

## 7. Documentation and Operability

README documents:

- how to run the main Django application.
- how to run the auth service.
- how to run the React component.
- how to obtain an authentication token.
- how to call the protected endpoint.
- how to run the shared library tests.
- how shared-library versions reach each service.
- how to run the WordPress migration.
- how safely re-running the migration behaves, including `--prune`.
- how to compile SCSS (via the Vite build).
- how to run the verification scripts.
- important modeling and architectural decisions.
- what would be done differently with additional time.
- any places where an AI-generated default was deliberately retained over
  the developer's own preference, and why.

## 8. Project Verification

Before the assessment is considered complete:

- application test suites pass.
- shared-library tests pass independently.
- configured linting and formatting checks pass.
- configured frontend type checks pass.
- the React production build succeeds.
- SCSS compilation succeeds.
- migration idempotency has been verified.
- the documented local-development workflow can start the required
  services.
- `scripts/verify-fast.sh` passes: ruff (lint and format), mypy (strict) on
  the shared library, shared-library tests, `tsc --noEmit`, ESLint (with
  jsx-a11y), Prettier, Stylelint, and Vitest.
- `scripts/verify.sh` passes: everything in the fast script, plus both
  Django test suites on PostgreSQL, `makemigrations --check`, `vite build`
  (including SCSS), and an import idempotency check in which a second run of
  both imports creates and updates nothing.
- All verification runs inside containers; only Docker is required on the
  host.
- After `cp .env.example .env`, `docker compose up -d` (or `make up`) starts
  the WordPress source, both Django services and both PostgreSQL databases
  with no other setup step: development keys come from `.env.example`, and
  the React and CSS assets are built into the `web` image.
- The main app starts and serves public pages when the auth service is not
  running.
- Only the auth service has access to the private signing key; the main app
  container has only the public key.
- The development key pair in `.env.example` is clearly labelled as
  development-only.
