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

### Data Migration

- WordPress brands are migrated into the Django application.
- WordPress reviews are migrated and associated with the correct brands.
- WordPress industry relationships are migrated.
- Reviewer identity is preserved.
- Running the migration multiple times does not create duplicate records.
- Re-running the migration produces deterministic results for
  source-controlled data.
- **TBD:** behavior when locally editable data differs from WordPress
  source data.
- **TBD:** behavior when a previously imported WordPress entity no longer
  exists in the source.

### Server-Rendered Pages

- `/` renders a homepage containing a hero and recent reviews.
- `/brand/<slug>/` renders the corresponding migrated brand.
- `/review/<slug>/` renders the corresponding migrated review.
- Brand and review URLs preserve the WordPress slugs.
- Requests for nonexistent brand or review slugs return an appropriate
  404 response.
- Recent-review ordering is deterministic.

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
  - industry
  - average rating
  - review count
  - short description
  - top review snippet

- **TBD:** authoritative source/calculation for average rating.
- **TBD:** definition and initialization of short description.
- **TBD:** definition of "top review."
- **TBD:** exact filtering, sorting, pagination, and error-response
  contracts.

### Protected Brand Update

A write endpoint for editing a brand's short description:

- requires authentication.
- rejects invalid or missing authentication.
- rejects an authenticated user without editor permission.
- allows a user with editor permission to update the short description.
- does not permit modification of fields outside the endpoint's intended
  scope.
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
- supports keyboard interaction for interactive controls.
- uses appropriate semantic HTML.
- meets basic accessibility expectations.
- is usable on mobile and desktop viewport sizes.
- **TBD:** filter cardinality.
- **TBD:** pagination interaction.
- **TBD:** URL synchronization behavior.

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

## 5. Authentication and Authorization Service

### Service Boundary

- Authentication and authorization run in a separate Django service.
- The auth service has its own database.
- The main application does not store passwords.
- The main application does not own user roles or permissions.

### User Migration

- WordPress users exist in the auth service after migration.
- Re-running user migration does not create duplicate users.
- The chosen password migration/reset behavior is documented.

### Authentication

- Valid credentials can be exchanged for a token.
- Invalid credentials are rejected.
- **TBD:** token format and validation mechanism.

### Authorization

- At least `reader` and `editor` roles exist.
- The auth service is authoritative for role/permission assignments.
- An editor can call the protected brand-update endpoint.
- A reader cannot call the protected brand-update endpoint.
- **TBD:** WordPress-role-to-application-role mapping.
- **TBD:** token revocation and role-change propagation behavior.
- **TBD:** behavior when the auth service is unavailable.

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
- **TBD:** exact public API and Django coupling.

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