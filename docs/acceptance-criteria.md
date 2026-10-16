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
- Split fields by owner. WordPress owns `title`, `content`, ACF fields, `industry`, and `reviews`. 
  Overwrite on each import. Django owns `short_description`. Import sets it only when it creates 
  a brand and never overwrites it after that.
- Report, don't delete when a previously imported WordPress entity no longer
  exists in the source. After import finishes, print brands and reviews that exist in Django but are
  missing from WordPress. Add a `--prune` flag on import to clean django data.
- The import reads the WordPress MariaDB database directly. The main app's
  `import_wordpress` imports industries, brands, reviewers and reviews; the
  auth service's `import_wordpress_users` imports users, password hashes and
  roles. The two commands are independent and can run in either order.
- Each import runs in a single transaction: a failure leaves no partially
  imported data.
- Imported rows are matched to their source by WordPress ID.
- Only published WordPress content is migrated.
- Dates are taken from `post_date_gmt` and stored in UTC.
- A brand's industries are replaced to match the source on every run.
- A changed WordPress slug updates the Django slug on the next run; the old
  URL is not redirected.
- The import prints a summary of created, updated, unchanged and missing
  records, and reports any review whose `reviewer_name` differs from its
  author's display name.
- The import never writes to the WordPress database.

### Server-Rendered Pages

- `/` renders a homepage containing a hero and recent reviews.
- `/brand/<slug>/` renders the corresponding migrated brand.
- `/review/<slug>/` renders the corresponding migrated review.
- Brand and review URLs preserve the WordPress slugs.
- Requests for nonexistent brand or review slugs return an appropriate
  404 response.
- Recent-review ordering is deterministic.
- Brand and review body HTML is stored exactly as in WordPress and cleaned
  when rendered by a single `|clean_html` template filter (nh3):
  - only allowlisted tags survive (`p`, `br`, `strong`, `em`, `a`, `ul`,
    `ol`, `li`, `blockquote`, `h2`–`h4`), and the only allowed attribute is
    `href` on links;
  - `<script>`, event-handler attributes and `style` never appear in the
    output;
  - links may only use `http`, `https` or `mailto`; `javascript:` links are
    removed;
  - this filter is the only place stored HTML is marked safe, and tests
    cover known XSS payloads.

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
- Average rating is derived from review ratings, API returns mean rounded to one decimal
  while sorting uses unrounded decimal. No reviews returns `null` and sorts last. Use slug
  for tie breaking. Calculated per request; a stored copy can be added later if scale requires it. Keep `average_rating` value
  from WordPress as `legacy_average_rating` for auditing.
- `short_description` editable text field is seeded from `post_excerpt` value in WordPress data (if present)
  If not present, use ~22 words of `post_content` value (cleaned and stripped of tags)
    - PATCH validation:
        - must be a non-empty string;
        - maximum length 300 characters (after trimming);
        - surrounding whitespace trimmed;
        - HTML treated as text.
- "Top Review" is determined by the most representative review, that which is closest to the brand's derived average of review scores.
    - Ties are detected exactly (integer arithmetic, not floats) and broken by:
        - lower rating of the two
        - then the most recent
        - then the WordPress ID
    - The snippet includes review slug, title, rating, reviewer name, and roughly the first 160 characters of plain-text body.
    - A brand with no reviews returns null.
- Filter, sort, pagination, and errors:
  - Filter: industry=<slug>, repeatable. An unknown slug returns 400, because industries are a closed, known set.
  - Sort: ordering=average_rating|-average_rating|review_count|-review_count. Default is -average_rating, with slug as the tie-break.
  - Pagination: page and page_size (default 12, maximum 50). The envelope is {count, next, previous, results}.
  - Errors: an invalid parameter returns 400 with {"errors": {"<param>": ["..."]}}. An out-of-range page returns 404.
- Filtering by several industries returns brands in any of them. A brand in
  more than one selected industry appears once, and its review count and
  average rating are not inflated.
- `legacy_average_rating` is not returned by the API.

### Industries

`GET /api/industries/`:

- is publicly accessible.
- returns every industry (slug and name), independent of which brands are
  on the current page or match the current filter.

### Protected Brand Update

A write endpoint for editing a brand's short description:

- requires authentication.
- rejects invalid or missing authentication with 401.
- rejects an authenticated user without editor permission with 403.
- allows a user with editor permission to update the short description.
- does not permit modification of fields outside the endpoint's intended
  scope.
- leaves public GET endpoints and server-rendered pages accessible without
  authentication.
- records every successful update in an audit log: the user (token `sub`),
  token ID (`jti`), timestamp, and the before and after values.

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
- includes a single-select `<select>` element with an "All industries" option. 
  The API still accepts repeated values for future expansion to multi-select.
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
- Each service uses its own PostgreSQL database in its own container
  (`main-db`, `auth-db`), so either can fail independently. Tests run
  against PostgreSQL.
- The main application does not store passwords.
- The main application does not own user roles or permissions.
- The main application never sees passwords or refresh tokens.

### User Migration

- WordPress users exist in the auth service after migration.
- Re-running user migration does not create duplicate users.
- The chosen password migration/reset behavior is documented.
- WordPress `$wp$` password hashes are copied as-is. Migrated users log in
  with their existing WordPress passwords; a wrong password is rejected.
- After a successful login, the password is re-hashed with Django's
  hasher.

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

### Authorization

- At least `reader` and `editor` roles exist.
- The auth service is authoritative for role/permission assignments.
- An editor can call the protected brand-update endpoint.
- A reader cannot call the protected brand-update endpoint.
- WordPress-role-to-application-role mapping: "administrator" becomes "editor", "subscriber" becomes "reader".
  Unknown roles map to "reader". Only "editor" role can PATCH.
- Role changes and deactivation take effect at refresh: every refresh
  reloads the user from the auth database, refuses inactive users, and
  builds the new access token's roles from the user's current roles (never
  copied from the old token).
- A demoted or deactivated user can act for at most one access-token
  lifetime (about 5 minutes). Observable: log in as an editor, demote the
  user, refresh; the new access token has no editor role and PATCH returns
  403.
- When auth service is unavailable, public GET endpoints and server-rendered pages are unaffected.
  PATCH with a valid, unexpired token still succeeds. Login and refresh fail.
- The main app receives the auth service's public key through
  configuration at deploy time and never fetches it from the auth service
  at runtime. If the key is missing, the main app fails at startup with a
  clear configuration error.

## 6. Shared Python Library

- Shared code is implemented as a separate installable Python package.
- The package has its own `pyproject.toml`.
- Both Django services install a defined version of the package.
- The package contains only functionality genuinely shared by the
  services.
- Shared authentication/token functionality required by the main
  application is provided through the package.
- Shared permission-checking functionality required by the main
  application is provided through the package.
- The package has tests that run independently of either Django project.
- Package installation/versioning and upgrade behavior are documented.
- The package defines the token contract (claim names, issuer/audience,
  signing algorithm) and role/permission names in one place.
- The core (claims, permissions, token verification) is plain Python plus
  PyJWT with no Django dependency. DRF authentication and permission
  classes live in an optional submodule.
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
- how safely re-running the migration behaves.
- how to compile SCSS.
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