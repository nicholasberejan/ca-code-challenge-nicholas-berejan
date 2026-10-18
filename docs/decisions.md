# Architecture Decisions

## 1. Schema Modeling

### Source identity

**Decision:** every imported entity keeps its immutable WordPress ID as its source identity, in a unique column separate from the Django primary key:

- `Industry`: Django PK, unique `wp_term_id`, `slug`, `name`.
- `Brand`: Django PK, unique `wp_post_id`, `slug`, …
- `Review`: Django PK, unique `wp_post_id`, `slug`, …
- `Reviewer`: Django PK, unique `wp_user_id`, `display_name`.
- The auth service's users likewise keep a unique `wp_user_id`.

**Rationale:** slugs are public routing identifiers and can change in WordPress; IDs cannot. The importer matches rows by WordPress ID, so a changed slug updates the existing row instead of creating a duplicate.

**Alternatives considered:** matching on slug was rejected, because a slug change in WordPress would create a second Django row and leave the old one (with its editor-owned `short_description`) behind.

### Reviewers

**Decision:** a content-owned `Reviewer` model (`wp_user_id`, `display_name`). `Reviewer` is owned by the main app and represents the public persona, not the account. Only WordPress users who authored reviews become Reviewers. `Review` has a FK to `Reviewer`, and queries listing reviews use `select_related("reviewer")` to avoid N+1 queries.

**Rationale:** this separates the account (credentials and roles, owned by the auth service) from the public persona (main app). Public pages never depend on the auth service.

**Alternatives considered:**

- Django users: rejected because it would introduce a second user table with password and permission columns, leading to two sources of truth.
- Plain strings on each review: rejected because names aren't unique, so identity is lost.
- Fetching names from the auth service at render: rejected because public pages would break when the auth service is down.

### Reviewer name

In the WordPress data, a review also has a `reviewer_name` field. I believe the intention is that a review could carry a name that differs from its author's `display_name` (for example, someone entering a review on behalf of someone else). However, in the seed data no review's `reviewer_name` differs from its author's display name. I decided to show the Reviewer's `display_name` on every review for consistency and not store `reviewer_name`; the name is reached through the FK. The importer reports any mismatches. A byline field could be added to `Review` later if users can submit reviews on behalf of others.

### Reviewer location

I initially thought the seed data suggested a design flaw, with the review owning the location rather than the reviewer. Looking closer, one brand (SwiftStream, an ISP) indicates regional service, so the location describes where the service was used, not where the reviewer currently lives. `reviewer_location` stays on `Review`.

### Industries

WordPress allows a brand to have more than one industry, although every seeded brand has exactly one. Brand ↔ Industry is many-to-many, so the model doesn't rule this out in future. Consequence: industry filtering must not inflate aggregates (see §4).

### Average rating

**Decision:** derived from `Review` rows and calculated per request. The WordPress `average_rating` value is stored as `legacy_average_rating` as source/audit information only. It is never returned by the API, displayed, or used for sorting.

**Rationale:** the stored value contradicts the reviews for 4 of 5 existing brands (for example, HomeShield Pro has a stored value of 3.9 but its reviews average 3.08).

**Tradeoffs:** the average is recalculated on each request, which is negligible at 60 reviews. With more scale, a stored copy could be updated on import or write. API representation is in §4.

### Short description

`Brand.short_description` is stored, editable plain text, seeded on import from `post_excerpt` when present, otherwise from ~22 words of `post_content` with tags stripped and entities decoded. The PATCH endpoint must edit this field, so it cannot be derived. The trim matches what the WordPress theme displays on cards.

A seeded value is stored as-is even if it exceeds the 300-character PATCH limit (§4); the limit applies only to edits. No current data is affected, since every seeded brand has an empty excerpt.

### No user accounts or Django admin in the main app

The main app stores no users, passwords, roles or permissions; the auth service owns all of them. API requests are identified by a lightweight, non-persisted principal built from the verified token by the shared library's DRF authentication class. The main app has no Django admin, because the admin requires local accounts with passwords, and migrating the WordPress admin is out of scope. Consequence: brand edits happen only through the protected PATCH endpoint; all other content comes from the WordPress import.

## 2. WordPress Postmeta Strategy

- The source has 10 postmeta rows per brand: 4 ACF values, 4 ACF field-key references, 2 Yoast fields.
- First-class fields (WordPress postmeta to Django model fields): brand `website_url`, `founded_year`, `headquarters`, `average_rating` (as `legacy_average_rating`); review `rating`, `reviewer_location`; review `brand` becomes an FK.
- Nothing is stored as JSON: every retained value has a known type and its own column.
- Every postmeta key is either mapped to a field or explicitly listed as dropped. The importer reports any key that is in neither list, with how many posts carry it, instead of silently ignoring it or storing it as JSON. A real site carries many more keys than this seed (editor bookkeeping such as `_edit_lock`, Yoast scores); new ones are surfaced for a deliberate decision.
- Dropped fields: the `_<field>` → `field_…` ACF key references (ACF plumbing); review `reviewer_name` (redundant with `Reviewer.display_name`; mismatches are reported by the importer).
- Yoast `_yoast_wpseo_title` / `_yoast_wpseo_metadesc` are dropped. They contain hand-written copy that goes stale (e.g. review counts). Brand pages generate `<title>` from the brand name and `<meta name="description">` from the `short_description`, which editors keep current. Accepted loss: editor-tuned SEO copy (retained in the WordPress dump); search snippets will change after cutover.

## 3. Migration Strategy

### Source: direct reads from WordPress's MariaDB

**Decision:** import management commands read the WordPress database directly with SQL over the Docker Compose network.

**Rationale:** MariaDB is the only source containing everything, including password hashes and roles.

**Alternatives considered:**

- WordPress REST API: rejected because it can't supply password hashes or roles.
- Parsing `db/dump.sql`: rejected because parsing SQL text is fragile and repeats work the database already does.

### Two independent commands

- Main app `import_wordpress`: industries, brands, reviewers, reviews.
- Auth service `import_wordpress_users`: users, password hashes, roles. WordPress roles are stored PHP-serialized and parsed with `phpserialize`. This import only creates users: an account that already exists (matched by `wp_user_id`) is never modified. After cutover the auth service owns the whole account, so re-running the import must not overwrite a changed role, a deactivation, or a password already upgraded to Django's hasher.
- Each service imports only what it owns. The main app never references auth accounts, so load order doesn't matter.

### Re-runnability and field ownership

- Rows are created or updated by WordPress ID (see §1, Source identity). Each command runs in a single transaction, so a failure leaves nothing half-imported.
- WordPress-owned fields (title, content, slug, ACF values, industries, reviews) are overwritten on every run, and a brand's industries are replaced to match the source. Rows whose source data hasn't changed are not written, so a second run reports nothing created or updated.
- `short_description` is set only when a brand is first created, so editor changes survive re-imports. Later WordPress excerpt changes do not flow through; this is a one-way cutover.
- Slug changes: our slug follows WordPress's on every run. If a slug changes in WordPress, the old URL stops working; no redirects are kept.
- HTML content is sanitized during import before it is stored (see §9).
- The command prints a summary of created, updated, unchanged and missing records, and lists any unrecognised postmeta keys (§2).

### Entities missing from the source, and `--prune`

**Decision:** by default, entities that exist in Django but are missing from WordPress are reported and not deleted. Destructive synchronization requires an explicit `--prune` flag, and runs inside the same transaction as the import. With `--prune`:

- A source-deleted **Review** is deleted.
- A source-deleted **Brand** is deleted together with its reviews; reviews belong to their brand and have no meaning without it.
- A **Reviewer** left with no reviews after the steps above is deleted. Without `--prune`, such orphaned Reviewers are reported.
- A source-deleted **Industry** is deleted (and removed from brands), so the filter options stop offering it.

Related rules:

- A review whose brand is not in the imported source (unpublished or deleted) is skipped and reported, never attached elsewhere. A skipped review already in Django is treated like any other missing row: kept unchanged (on its previous brand) and reported until `--prune` deletes it. Accepted tradeoff: if WordPress moves a review to an unavailable brand, its old brand keeps showing and counting it until the next `--prune`; in a one-way cutover the final import runs with `--prune`. With more time: a "missing from source" flag that hides such rows from public pages instead of keeping them visible.
- `Review` → `Reviewer` uses a protecting FK, so a Reviewer can never be deleted while reviews still reference it.
- The auth service's import never deletes users; users missing from WordPress are only reported. Removing an account is an access-control decision and should be made deliberately (for example by deactivating the user).

**Rationale for orphaned Reviewers:** a Reviewer exists only as the public persona of a review author (§1) and holds no other data. Keeping orphans would break that rule and leave rows nothing displays.

**Possible future improvement:** a `--dry-run` mode that reports what `--prune` would delete without deleting it.

### Other import rules

- Only published content is migrated.
- Dates come from `post_date_gmt` (UTC).
- Role mapping: `administrator` becomes `editor`, `subscriber` becomes `reader`, unknown roles become `reader`.

### Connection

A separate connection alias used only for reads. Local development reuses the `wp` user, which can write, so read-only is enforced by our code and a router (which also blocks migrations against the alias) rather than by the database; production would use a read-only user or replica. Commands run inside the service containers, and only the WordPress `db` service needs to be running.

### Scaling

At 100x the data: batched/chunked reads, and `bulk_create(update_conflicts=True)` instead of per-row upserts.

## 4. Brand API Contract

### Top review snippet

**Decision:** the top review is the review whose rating has the smallest absolute distance from the brand's derived mean rating. Ties are broken in this order:

1. If two reviews are equally distant from the mean, prefer the **lower** rating.
2. Then prefer the most recent review.
3. Then use the WordPress post ID as the final deterministic tie-breaker.

The lower-rating preference applies **only** when two reviews are equally distant. If an above-mean rating is closer to the mean than a below-mean rating, the closer one wins. For example, with a mean of 3.6, a 4 (distance 0.4) beats a 3 (distance 0.6); with a mean of 3.5, a 3 beats a 4.

Brands with no reviews return `null`. Distance is compared with integer arithmetic, `abs(rating × review_count − rating_sum)`, so equal distances compare as equal without floating-point issues.

The snippet contains the review's slug, title, rating, reviewer display name, and roughly the first 160 characters of its plain-text body.

**Rationale:** select the review closest to the aggregate sentiment, without systematically presenting the most favorable review; a platform serving consumers as well as brands shouldn't default to a brand's best review. On exact ties, erring toward the lower rating deliberately favors the more critical consumer experience.

**Alternatives considered:**

- Highest-rated review: simple, deterministic and easy to document, but rejected because it systematically favors the brand.
- "Closest without going over" (always prefer a below-mean review): rejected because it picks a below-mean review even when an above-mean review is objectively closer.

**Tradeoffs:** for a brand with split opinions (all 1s and 5s), the closest review may not represent anyone's actual experience, and the pick may be a bland middle-of-the-road review. With more time: show one positive and one critical review per card. At scale, selection moves into the database, like the average: a stored copy of each brand's top review updated on import (reviews only change through the import), or one PostgreSQL `DISTINCT ON` query per page. Today the winners are chosen in Python from the current page's review ratings, which is exact and takes a constant number of queries but reads every review of those brands.

### Average rating representation and sorting

**Decision:** `average_rating` is a JSON number rounded to two decimal places (e.g. `3.92`), or `null` for a brand with no reviews. Sorting always uses the underlying, unrounded derived average. Brands with no reviews sort last in either direction; ties are broken by slug. Display formatting (e.g. "3.9" on a card) belongs to the UI.

**Rationale:** two decimal places represent the aggregate meaningfully on a 1–5 scale, give a deterministic, readable value, and keep presentation out of the contract. Rounding happens only in the serializer; the ordering uses the database aggregate.

**Alternatives considered:**

- One decimal place in the API: rejected because it puts presentation into the contract and discards information (3.92 and 3.88 both become 3.9).
- Unrounded float: rejected because it exposes floating-point noise (e.g. `3.9166666666666665`).
- Decimal serialized as a string (DRF's default): rejected because every client would have to parse it.

### Industry filter options

**Decision:** a simple `GET /api/industries/` endpoint serves every industry (slug, name), and the React select is populated from it.

**Alternatives considered:**

- Hard-coding options in the frontend select component: rejected because every new industry would need a frontend change.
- Deriving options from the brand listing response: rejected because a paginated page doesn't guarantee every industry appears, and once a filter is applied the other industries would vanish from the options.

CHALLENGE.md asks for "a single endpoint" serving the brand listing data. I read that as referring to brand listing data; industries are a distinct resource.

### Industry representation and filtering

Each brand row returns `industries: [{slug, name}]`. Filtering by industry matches brands in any of the requested industries. Filtering is implemented as a subquery (`pk__in=Brand.objects.filter(industries__slug__in=...).values("pk")`), so the outer query never joins industries and aggregates are never inflated. Without this, a brand matching two selected industries would report double its review count. `distinct()` was considered but rejected: it removes duplicate rows but not inflated counts.

### Filter, sort, pagination and errors for `GET /api/brands/`

- Filter: `industry=<slug>`, repeatable (matches brands in any of the given industries). An unknown slug returns 400, because industries are a closed, known set.
- Sort: `ordering=average_rating|-average_rating|review_count|-review_count`. Default is `-average_rating`, with slug as the tie-break.
- Pagination: `page` and `page_size` (default 12, maximum 50). The response envelope is `{count, next, previous, results}`.
- Errors: an invalid parameter returns 400 with `{"errors": {"<param>": ["..."]}}`. An out-of-range page returns 404. Every error returned by an API view uses this one shape: invalid parameters (400), an out-of-range page (404), and errors DRF raises itself (405, 406, and later 401/403). Errors not tied to a parameter or field use the key `detail`, e.g. `{"errors": {"detail": ["Method \"POST\" not allowed."]}}`. One DRF exception handler applies it. Not covered: URLs that match no API route (Django's 404 page) and unhandled server errors (500).

### Why this contract shape

- **Page-number pagination** supports the "Page X of Y" control, deep links to a specific page, and a total count, and costs nothing at this data size. Cursor pagination was not needed for a small, rarely changing list.
- **`ordering`** is DRF's convention for sort parameters, with `-` for descending.
- **`industry` is repeatable**, so moving the UI to multi-select needs no API change.
- **400 for unknown values** instead of silently ignoring them, so client bugs surface immediately.

### If a mobile client also consumed the API

- Version the path (`/api/v1/`), because installed app versions can't be force-upgraded and the contract must stay stable for older clients.
- Offer cursor pagination for infinite scroll; it stays stable when data changes between page requests.
- Keep `next`/`previous` as absolute URLs (DRF's default) so clients never construct them.
- Add caching headers (ETag / `Last-Modified`) to save bandwidth on mobile networks.
- No auth change: JWT access tokens plus refresh tokens already suit a native client.

### PATCH endpoint

`PATCH /api/brands/<slug>/` with a JSON body containing only `short_description`. A successful update returns 200 with the updated brand in the same shape as a listing row.

### PATCH validation

`short_description` must be a non-empty string; maximum length 300 characters (after trimming); surrounding whitespace trimmed; HTML treated as plain text.

## 5. React Component and State

- Cards show one industry badge per industry, sorted by name (the WordPress theme showed only the first).
- Cards display the average rating formatted to one decimal place; this is presentation only (the API sends two decimal places, see §4).
- Industry filter: a single-select `<select>` with an "All industries" option. The API still accepts repeated `industry` values, so the UI can move to multi-select later without an API change.
- URL synchronization:
    - Filter, sort and page live in the query string with the same names as the API; default values are omitted.
    - User changes push a new history entry (`pushState`); `popstate` re-reads the URL.
    - Invalid URL values fall back to defaults instead of erroring.
    - Observable: a deep link reproduces the view, and Back restores the previous filter.
- Pagination: Previous and Next buttons driven by the API's `previous`/`next` links, with a "Page X of Y" label. A button is disabled (not hidden) when there is no page in that direction. After a page change, keyboard focus moves to the results heading so keyboard and screen-reader users land on the new results. Changing the filter or sort resets to page 1. Chosen over numbered page links because there are currently 5 brands (a single page at 12 per page).

### Loading, empty and error UX

- **Loading:** on first load, a loading message; on later changes, the previous results stay visible but dimmed, with `aria-busy="true"` on the results region, so the page doesn't jump.
- **Result count:** "N brands" is announced through a polite live region (`aria-live="polite"`) after each load.
- **Empty:** a "No brands match" message with a button that clears the filter.
- **Error:** an error message with a Retry button that repeats the last request; the filter and sort controls stay usable.

### State ownership

**Decision:** the URL owns the user's choices (filter, sort, page); a small `useUrlParams` hook reads and writes them. Fetched data comes from small custom hooks (`useBrands(params)`, `useIndustries()`) using `fetch` with an `AbortController`, so a slow, stale response can never overwrite a newer one. Each hook exposes explicit loading, error, empty and loaded states. `BrandList` owns the hooks and passes values down as props to small presentational children (`IndustryFilter`, `SortSelect`, `BrandCard`, `Pagination`).

**Component split:** `BrandList` stays the orchestrator: it owns the URL state, the data hooks and every URL- or API-dependent decision about which state to show (including the URL fallbacks that suppress an error). Its presentational children receive plain props and know nothing about the URL or the API:

- `IndustryFilter`, `SortSelect`: the controls.
- `BrandResults`: a loaded page: the busy wrapper (`aria-busy`), the empty state with its clear-filter action, the card grid (`BrandCard`) and `Pagination`.
- `LoadError`: a failed request (`role="alert"`, message, Retry).

The one-line loading message stays inline in `BrandList`: it has no logic, and extracting it would only add a component for symmetry.

**Alternatives considered:**

- SWR / TanStack Query: rejected as overkill. Their caching, de-duplication and revalidation don't pay for a dependency with one component and two endpoints. Switching later would only change the inside of `useBrands`.
- Context provider: rejected. Context solves sharing state across distant parts of a component tree; every consumer here is a direct child of `BrandList`, so props are enough.
- Redux / Zustand: rejected as overkill for a single component's state.

## 6. SCSS Architecture

- One styling system: the React component reuses the same SCSS classes as the server-rendered pages (`.card`, `.badge`, `.stars`, …). Tailwind (allowed for the React component by CHALLENGE.md) was rejected because it would mean two styling systems for the same cards and badges.
- Source tree under `frontend/scss/`, compiled with Dart Sass using `@use`/`@forward` (the older `@import` is deprecated):
    - `main.scss`: entry point, contains only `@use` lines.
    - `abstracts/`: `_tokens.scss` (colours, radius, shadows, spacing, type sizes), `_mixins.scss` (breakpoint mixin). Emit no CSS on their own.
    - `base/`: `_reset.scss`, `_typography.scss` (element defaults: html/body, links, images).
    - `layout/`: `_container.scss`, `_header.scss`, `_footer.scss`, `_grid.scss`, `_section.scss`.
    - `components/`: `_card.scss`, `_stars.scss`, `_badge.scss`, `_pagination.scss`, `_brand-list.scss`.
    - `pages/`: `_home.scss`, `_brand.scss`, `_review.scss`, `_page.scss`.
- Tokens: the theme's CSS custom properties (`--color-primary`, etc.) stay as the runtime layer, generated from one SCSS token map so each value is defined once. Hard-coded values the theme repeats outside its token set (some of its hex colours, spacing, font sizes) become tokens too.
- Naming: keep the theme's component names (`.card`, `.badge`, `.stars`), but replace structure-dependent selectors like `.card h3 a` with BEM-style element classes like `.card__title`. Each class styles one thing, so a new component can't break an existing one.
- Rules: nest at most two levels; each partial owns exactly one component or layout region; only `pages/` may contain page-specific styles; all media queries go through the breakpoint mixin.
- The SCSS is compiled by the Vite build (see §11).

## 7. Authentication Service Boundary

### Ownership

The auth service is responsible for user accounts (login names, active status), credentials, roles/permissions, processing login (checking credentials and active status), token refresh/revocation, and user import. It holds the private key that signs tokens; the matching public key is given to the main app. The main app verifies tokens through the shared library, never seeing passwords or refresh tokens, and enforces the permission: 401 for an invalid or missing token, 403 for a valid token without permission.

### User model, roles and administration

- The auth service uses a custom Django user model (`AbstractUser` plus a unique `wp_user_id`), created before the first migration as Django recommends. WordPress `user_login` becomes `username`; `user_email` becomes `email`; the WordPress hash goes into the standard `password` field.
- Roles are Django groups named `reader` and `editor`. A token's `roles` claim lists the user's groups that are known roles.
- The auth service enables the Django admin. Unlike the main app, it owns real user accounts with passwords, so the admin works as designed. Operators use it to change a user's roles, deactivate a user, and revoke sessions.
- WordPress administrators are imported with admin access (`is_staff`, `is_superuser`) in addition to the `editor` role, so the existing WordPress admin can operate the auth admin after cutover.

### Endpoints

- `POST /api/token/` with `username` (the WordPress login name) and `password`: returns an access token and a refresh token.
- `POST /api/token/refresh/` with a refresh token: returns a new access token and a new (rotated) refresh token.
- `POST /api/token/logout/` with a refresh token: blocks it, ending that session.

### Revocation

- A role change or deactivation in the admin takes effect at the user's next refresh (see Refresh tokens), within one access-token lifetime.
- To end a user's sessions without changing their roles, an admin action blocks all of that user's outstanding refresh tokens (simplejwt's token blacklist). Their current access token still works until it expires.

### Local token verification

**Decision:** short-lived access tokens that the main app verifies locally with an RS256 public key, renewed with a longer-lived refresh token so users don't have to log in every ~5 minutes.

**Rationale:** traffic is small, reads are public, and there is only one protected endpoint (PATCHing a brand's short description). Local verification keeps the auth service off the request path.

**Alternatives considered:** a live permission check against the auth service on every PATCH, or opaque tokens introspected on each request. Both give immediate revocation but put the auth service on the write path, so writes fail whenever it is down.

### Access tokens

5-minute RS256 JWTs with claims `sub`, `roles`, `iss`, `aud`, `exp`, `iat`, `jti`. The main app verifies signature, expiry, issuer and audience locally with the public key. RS256 was chosen over HS256 because with HS256 the same secret signs and verifies, so the main app could mint its own editor tokens; with RS256 only the auth service can sign, and the main app can only verify.

### Refresh tokens

~1-day refresh tokens, rotated on every use; used or revoked refresh tokens are blocked. The refresh token carries only the user's identity, never roles. On every refresh the auth service reloads the user from its database: an inactive or deleted user is refused, and the new access token's `roles` come from the user's *current* role assignments.

- Why this matters: an access token's roles are a snapshot taken when it was issued, and the main app trusts that snapshot until the token expires. Refresh is the only point where a role change reaches a user's tokens, so reloading roles there is what limits the demotion window to one access-token lifetime (~5 minutes).
- Risk: simplejwt's default refresh copies claims from the old refresh token, and with rotation the stale claims carry forward into each new refresh token. If roles were copied, a demoted editor could keep obtaining editor tokens indefinitely. The implementation overrides this behaviour.
- Required tests: (1) log in as an editor, demote the user, refresh, and assert the new access token has no editor role and the PATCH returns 403; (2) deactivate a user and assert refresh is refused.

### Role staleness: a bounded tradeoff

**Decision:** an already-issued access token keeps the roles it was issued with until it expires. A demoted or deactivated user can therefore act for at most one access-token lifetime (~5 minutes). This is a deliberate, bounded consistency/security tradeoff, accepted because the only protected operation is editing a brand's short description: low impact and easily corrected by another editor. No audit log, undo mechanism, or other compensating subsystem is built.

**Alternatives for a system needing immediate revocation:** token introspection on each protected request; a per-user token/authorization version that the main app checks; centralized authorization (the main app asks the auth service on every protected request); or a shared denylist of revoked token IDs. Each puts the auth service, or a shared store, on the write path.

### Auth service outages

If the auth service is down, public pages and GET endpoints are unaffected, because they are public and the main app never calls the auth service. PATCH with a still-valid token works until the token expires. Login and refresh fail.

### Public key distribution

The auth service's public key is supplied to the main app at deploy time as configuration (an environment variable; see §13); the main app never fetches it from the auth service at runtime. The key is therefore always available, and a missing key is a startup configuration error rather than a request-time failure. Tradeoff: rotating the key means redeploying the main app. With more time: publish keys at a JWKS endpoint for easier rotation, which would then require deciding what PATCH returns when keys can't be fetched (503 rather than 401).

### Password migration: transitional compatibility

**Decision:** support the WordPress 6.8+ `$wp$` password hashes found in the source data (bcrypt over an HMAC-SHA384 prehash) by copying them as-is. A custom hasher in the auth service is a **transitional migration-compatibility mechanism**, not a permanent authentication scheme:

```
imported WordPress user
    -> existing $wp$ hash
    -> first successful login
    -> custom hasher verifies the legacy password
    -> Django re-hashes the password with its configured native hasher
    -> subsequent logins use the normal Django hash
```

**Rationale:** users keep their existing passwords; nobody has to reset anything at cutover.

**Tests:** against known seed credentials: a correct password succeeds, an incorrect password is rejected, and after the first successful login the stored hash is Django's native format and the same password still works.

**Tradeoffs:** security-sensitive code we own (small, but needs careful tests, plus a `bcrypt` dependency). Only the `$wp$` format actually present in this data is supported; older WordPress formats (`$P$`) are not required. Users who never log in keep the legacy hash.

**Alternatives considered:**

- Unusable passwords plus an admin-driven reset: rejected because nobody can log in until a manual step.
- One shared known password: rejected as an insecure pattern.

## 8. Shared Library

### What goes in it

The package holds two kinds of code, and not every module is executed by both services:

- **Cross-service contracts**, used by both services: claim names, issuer/audience expectations, signing algorithm, and role/permission constants. The auth service issues tokens with them; the main app verifies against them. Defining the contract in one place means the issuer and verifier can't silently disagree about the token's format.
- **Consumer-side authentication infrastructure**, used primarily by the main app: `verify_token` and the DRF authentication and permission classes. It belongs in the package because CHALLENGE.md explicitly requires the token verification and permission-check code there, and any future service that protects endpoints would reuse it.

Token signing stays in the auth service, the only service holding the private key.

### Structure

- The core (claims, permissions, verification) is plain Python plus PyJWT, with no Django dependency.
- The DRF classes live in a submodule offered as an optional install. The auth service installs only the core; the main app installs the core plus the DRF classes.

### Tests

Core tests run with pytest alone. The DRF classes are tested with a minimal Django configuration inside the package's test suite, not either service's project.

### Distribution: local wheelhouse

**Decision:** releasing the library means bumping the version in its `pyproject.toml` and building a wheel into a `wheels/` directory in the repo. Each service pins an exact version (e.g. `shared-auth==1.2.0`) and installs it with `--find-links wheels/`, so each service upgrades only when its own pin changes.

**Rationale:** this is proportionate to the assessment. It demonstrates independent version pinning and staged upgrades; it is not meant to be a production package-distribution platform. Moving to a real private index later only changes the install flag.

**Alternatives considered:** a local path / editable install (rejected: both services always get whatever is on disk, so pinning can't be shown); a git URL plus tag (rejected: Docker builds would need GitHub access and pushed tags); a private index such as a `pypiserver` container (rejected: extra infrastructure for no benefit at this size); public PyPI (rejected: it would publish internal auth code).

### Breaking changes

Breaking changes ship expand-then-contract, with the verifier always upgrading before the issuer: (1) release v2 whose verifier accepts both old and new token formats; (2) deploy the main app on v2 (nothing changes yet); (3) deploy the auth service on v2, which starts issuing the new format; (4) once all old tokens have expired (refresh lifetime, ~1 day), release v3 without old-format support and roll it out to each service independently.

## 9. Additional Considerations

### DRF in both services

Main app: filtering, ordering, pagination, serializers, PATCH validation. Auth service: `djangorestframework-simplejwt` for login, refresh rotation and blocking used tokens. One framework and one set of conventions across both.

### PostgreSQL, one container per service

**Decision:** PostgreSQL 17, with separate `main-db` and `auth-db` containers, each with its own volume and credentials. Tests run against PostgreSQL.

**Rationale for PostgreSQL:** migrations run inside transactions and roll back cleanly on failure (MariaDB can't roll back schema changes), and tests run on the same database as production.

**Rationale for separate containers:** CHALLENGE.md requires each service to have its own database; it does not require separate database servers. Separate containers are a deliberate stronger-isolation choice for this assessment:

- database ownership is explicit;
- accidental cross-service database coupling (shared credentials, cross-database queries) is impossible;
- the service/database boundary can be exercised independently (for example, stopping `auth-db` alone).

**Alternatives considered:**

- One PostgreSQL server with two logical databases and separate credentials: a reasonable and operationally simpler alternative at this scale, for development or production. Not chosen only because the stronger isolation is more useful to demonstrate here.
- MariaDB: rejected because it ties us to the system being retired and lacks transactional schema changes.
- SQLite: rejected because tests would run on a different database than production, and it is weak with concurrent writes.

### Server-rendered page content

- **Homepage (`/`):** a hero with text written in the template, followed by the 6 most recent reviews (newest first by publish date, then WordPress ID).
- **Brand page (`/brand/<slug>/`):** brand name, one badge per industry, derived average rating to one decimal place with review count, website, founded year, headquarters, body, and all of the brand's reviews, newest first.
- **Review page (`/review/<slug>/`):** link back to its brand, title, rating, reviewer display name and location, publish date, and body.
- **Brand listing (`/brand/`):** the page where `<BrandList />` mounts.
- The WordPress Home, About and Contact pages are not migrated, and the header has no links to them; the header links to the homepage and the brand listing. CHALLENGE.md requires only the three pages above, and the static pages' content is placeholder text.

### HTML sanitization at import

**Decision:** imported WordPress HTML is sanitized at the trust boundary, during import, and stored sanitized:

```
WordPress HTML
    -> importer
    -> centralized sanitizer
    -> sanitized HTML stored in Django
    -> Django templates render the already-sanitized HTML
```

A single sanitizer function in the main app (using `nh3`) is the only HTML cleaner. Only allowlisted tags (`p`, `br`, `strong`, `em`, `a`, `ul`, `ol`, `li`, `blockquote`, `h2`–`h4`) and attributes (`href` on links) survive; event handlers (`onclick`, `onerror`…) and `style` are always removed; links may only use `http`, `https` or `mailto` (so `javascript:` links are removed). Tests feed it representative XSS payloads. Templates mark only these sanitized body fields safe; every other field is auto-escaped, including the plain-text `short_description`. Any future write path that accepts HTML must pass through the same sanitizer before persistence.

**Rationale:**

- Migration is the point where externally sourced WordPress HTML crosses into the new application's trust boundary.
- Sanitizing once avoids repeatedly sanitizing immutable imported content on every render.
- The application never marks unsanitized external HTML safe.

The Django database is not intended to be an exact WordPress mirror; the migration deliberately normalizes the WordPress domain. No raw copy of the HTML is kept alongside the sanitized one. If the allowlist changes, re-running the import re-sanitizes the content, because WordPress owns it and the import overwrites it.

**Alternatives considered:** sanitizing at render with a template filter, with HTML stored exactly as in WordPress. Rejected because it repeats work on every render and lets unsanitized external HTML persist inside the application.

**Tradeoffs:** safety depends on every HTML write path using the sanitizer. Today the import is the only such path.

## 10. Repo Layout and Runtime Versions

- One repository with one top-level directory per concern, matching the four boundaries:
    - `services/web/`: main Django app (brands, reviews, industries, API, pages, WordPress import).
    - `services/auth/`: auth Django service (accounts, roles, tokens, user import).
    - `packages/shared-auth/`: the shared library (`pyproject.toml`, `src/shared_auth/`, `tests/`).
    - `wheels/`: the wheelhouse of built library versions.
    - `frontend/`: React + TypeScript under `src/`, SCSS under `scss/`.
    - Separate repositories were rejected: more realistic, but graders need one checkout.
- Versions: Python 3.12, Django 5.2 LTS (supported to April 2028; Django 6.0 rejected for its shorter support window), PostgreSQL 17, Node 24 LTS (the host's Node 20 is end-of-life). The host's Python 3.9.6 and Node 20 are irrelevant because everything runs in containers.
- Python dependencies are managed with `uv`, with a lockfile per service for reproducible builds; it supports `find-links` for the wheelhouse. Plain `pip` with pinned requirements was rejected because it has no real lockfile.

## 11. Frontend Build

- Vite + React + TypeScript. One tool builds both the React bundle and the SCSS (Vite compiles SCSS natively with Dart Sass).
- Assets are built when the `web` Docker image is built: a first Node stage in `web`'s Dockerfile runs `npm ci && vite build`, and the Python stage copies the output into a directory Django serves as static files. `docker compose up` therefore always has built assets, with no always-on frontend service. The output lives outside the bind-mounted code directory so the dev bind mount doesn't hide it.
- Vite writes fixed file names (`brand-list.js`, `main.css`), served by Django's development server from the build baked into the `web` image. Content hashing (`collectstatic` with `ManifestStaticFilesStorage`) is deferred to production hardening. No `django-vite` package and no reading Vite's manifest.
- The server-rendered `/brand/` page outputs `<div id="brand-list">` and React mounts into it; every other page is plain Django templates.
- Local development: a React or SCSS change appears in the Django site after rebuilding the `web` image. For faster iteration on the component alone, `npm run dev` (Vite's dev server, forwarding `/api` to Django) runs behind a Compose `tools` profile (like the existing `wpcli`). A `vite build --watch` workflow that feeds the running site is deferred.
- Frontend tests: Vitest + React Testing Library + `user-event`.
- Rejected: Vite dev server with hot reload inside Django pages (needs `django-vite`, more moving parts); committing built assets to git (they go stale); serving the frontend from a separate server on another origin (needs CORS and a second server); an always-on `frontend` build service (a fresh start could serve pages before the first build finishes); webpack (slower, more config); a separate `sass` CLI (a second build step).

## 12. Verification Tooling

- All checks run inside containers, so only Docker is required. Frontend checks run in the `tools`-profile `frontend` container.
- Tools:
    - Python: ruff (lint + format); pytest + pytest-django against PostgreSQL; `manage.py check` and `makemigrations --check`.
    - mypy (strict) on the shared library only: it is small, plain Python and security-relevant. Typing both Django projects would need `django-stubs` plumbing that isn't worth it here.
    - TypeScript: `tsc --noEmit`, ESLint with `eslint-plugin-jsx-a11y`, Prettier.
    - SCSS: Stylelint with `stylelint-config-standard-scss`, `max-nesting-depth: 2` and a BEM class pattern, so the SCSS rules are enforced automatically.
- `scripts/verify-fast.sh` (no databases): ruff, mypy on the library, library tests, `tsc`, ESLint, Prettier, Stylelint, Vitest.
- `scripts/verify.sh` (full): everything in fast, plus both Django test suites on PostgreSQL, the migration check, `vite build` (which also compiles SCSS), and an import idempotency check that runs both imports twice and fails if the second run reports anything created or updated.
- Rejected: pre-commit hooks (another tool); the scripts are the single entry point, and a hook can call `verify-fast.sh` later.

## 13. Local Environment (Docker Compose)

- New services added to the existing `docker-compose.yml` alongside the WordPress services:
    - `web` (main app, port 8000), depends on `main-db` being healthy.
    - `main-db` (`postgres:17`).
    - `auth` (auth service, port 8001), depends on `auth-db` being healthy.
    - `auth-db` (`postgres:17`).
    - `frontend` (`node:24`), under the `tools` profile only: runs frontend checks, `vite build --watch`, or the Vite dev server (port 5173) on demand. It is not started by `docker compose up`.
- `web` does not depend on `auth`, so the main app starts and serves public pages while auth is down. Neither service depends on WordPress's `db`; the import commands report a clear error if MariaDB isn't running.
- Keys: one development-only RS256 key pair is committed in `.env.example` as two single-line (base64-encoded) variables, clearly labelled "DEV ONLY — production keys come from a secret store". CHALLENGE.md's setup (`cp .env.example .env && docker compose up -d`) therefore produces working keys with no extra step. Compose passes `JWT_PRIVATE_KEY` only to `auth`, so the main app never has the private key; both services receive `JWT_PUBLIC_KEY` (auth checks its own refresh tokens with it).
    - Tradeoff: anyone with the repository can mint tokens for their own local stack. This is harmless with seed data, and the keys must never be used outside local development.
    - Rejected: generating keys with a `make keys` step or a one-shot Compose service (an extra step or moving part that plain `docker compose up -d` would miss, leaving both services unable to start); hard-coding keys in application code (puts key material in source and mixes configuration with code).
- Dev servers: each service's entrypoint runs `migrate`, then `runserver`, with code bind-mounted so it reloads on save. With more time: production-style gunicorn.
- `.env.example` gains PostgreSQL credentials per service, a separate `DJANGO_SECRET_KEY` per service, `JWT_ISSUER`, `JWT_AUDIENCE`, the development `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`, and `WP_DB_*` for the importer.
- Makefile: `make up` starts everything. New targets: `import` (both import commands), `test`, `verify-fast`, `verify`, and `lib-release` (bump the library version and build a wheel into `wheels/`). Existing WordPress targets are unchanged.
- The Docker build context is the repo root, so each service installs its pinned `shared-auth` version from `wheels/`. Changing the library means release, bump the service's pin, rebuild, so each service upgrades on its own schedule.
