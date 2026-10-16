# Architecture Decisions

## 1. Schema Modeling

- Reviewers: a content-owned Reviewer model. Fields: `wp_user_id` (unique, import key), `display_name`, `id`. `Reviewer` is owned by the main app and represents the public persona, not the account. Only WordPress users who authored reviews become Reviewers. `Review` has a FK to `Reviewer`. Queries listing reviews use `select_related("reviewer")` to avoid N+1 queries. This model separates the account (credentials, roles, managed by the auth service) from the public persona (main app). Public pages never depend on the auth service.
    - Django users: rejected because it would introduce a second user table with password and permission columns, leading to two sources of truth.
    - Plain strings: rejected because names aren't unique, so identity is lost.
    - Fetching names from the auth service at render: rejected because public pages will break when the auth service is down.
- Reviewers have a display_name field, while in the WordPress data the Review also has a reviewer_name field. I believe the intention here is that a review can be created with a reviewer name that might differ from the author `display_name` of the post (like if another user is entering a review on behalf of someone else). However, in the seed data there are no reviews with reviewer_name that differs from their author's display_name. I am going to have the Reviewer's display_name show on all reviews for consistency and forgo the Review's "reviewer_name" field, since the name can be accessed by the Foreign Key to the Reviewer (we will use `select_related` to efficiently include the FK relation when querying reviews.) We could always add a byline to the Review model in the future if we want users to be able to submit reviews on behalf of others.
- Reviewer location: I initially thought the seed data suggested a design flaw wherein the review owned the location, as opposed to the reviewer, however after looking closer I see one brand (SwiftStream, an ISP) being reviewed indicates regional service, so it does make sense that the review would be for that area where it was used, not the Reviewer's current location. I have decided to keep the location on the Review model as a result.
- WordPress allows a brand to have more than one industry, although the seed data has no examples where any brand has more than one industry. I have decided the django app will also support more than one industry for a brand so that this functionality can be included in future updates. We will make a M2M relation to the Industry model for Brands.
- Average rating: derived, with legacy value retained. I decided on derived because the stored value contradicts the reviews for 4 of 5 existing brands (ex. HomeShield Pro has a stored value of 3.9, derived 3.08.) A brand's average rating is calculated from its reviews' ratings. The WordPress `average_rating` value is stored as `legacy_average_rating` for audit purposes, and is not returned by the API, used for sorting, or displayed. The derived value field could be cached and updated on write/import when scaling later.
- Short description: stored, editable, and seeded on import. `Brand.short_description` is an editable plain-text field, seeded from `post_excerpt` when present, otherwise from ~22 words of `post_content` but stripped of tags with entities decoded. The PATCH endpoint must edit this field, so it cannot be derived. The trim matches what the WordPress theme displays on cards.
- No user accounts or Django admin in the main app. The main app stores no users, passwords, roles or permissions; the auth service owns all of them. API requests are identified by a lightweight, non-persisted principal built from the verified token by the shared library's DRF authentication class. The main app has no Django admin unfortunately, because the admin requires local accounts with passwords (and migrating the WordPress admin is out of scope). Consequence: brand edits happen only through the protected PATCH endpoint, and content otherwise comes from the WordPress import.

## 2. WordPress Postmeta Strategy

- The source has 10 postmeta rows per brand: 4 ACF values, 4 ACF
  field-key references, 2 Yoast fields.
- First class fields (from WP postmeta to django model fields): brand `website_url`, `founded_year`,
  `headquarters`, `average_rating` (as `legacy_average_rating`); review
  `rating`, `reviewer_location`; review `brand` becomes an FK.
- Dropped fields: the `_<field>` → `field_…` ACF key references (ACF plumbing);
  review `reviewer_name` (redundant with `Reviewer.display_name`; mismatches
  are reported by the importer).
- Yoast `_yoast_wpseo_title` / `yoast_wpseo_metadesc` dropped. They contain hand-written copy that goes stale (e.g. review counts). Brand pages generate `<title>` from the brand name and `<meta name="description">` from the `short_description` which editors keep current. Acepted loss: editor-tuned SEO copy (retained in the WordPress dump); search snippets will change after cutover.

## 3. Migration Strategy

- Source: direct reads from WordPress's MariaDB. Import management commands read the WordPress database directly with SQL over the Docker Compose network. This was decided because the MariaDB is the only source containing everything including password hashes and roles, and the WordPress REST API rejected because it can't supply password hashes or roles.
- Two independent commands: main app `import_wordpress` (industries, brands, reviewers, reviews). Auth service `import_wordpress_users` (users, hashes, roles). Each service imports only what it owns. WordPress roles are stored PHP-serialized and parsed with `phpserialize`.
- Re-runnability: imported rows store their WordPress ID, rows are created or updated by that key. Each command runs in a single transaction, a failure leaves nothing half-imported. WordPress-owned fields (title, content, ACF values, industries, reviews) are overwritten on every run, and a brand's industries are replaced to match source. `short_description` is set only when a brand is first created, so editor changes survive re-imports. Later WordPress excerpt changes do not flow through, since this is a one-way cutover that seems right. Removed source entities are reported but not deleted: after import, brands and reviews that exist in Django but are missing from WordPress are printed. An explicit `--prune` flag deletes them from Django; without it, nothing is deleted.
- Only published content is migrated.
- Dates come from `post_date_gmt` (UTC)
- Role mapping: administrator becomes editor, subscriber becomes reader, unknown roles become readers.
- Scaling: As brands and reviews grow, implement batched/chunked reads and use `bulk_create(update_conflicts=True)`
- How the connection works: a separate connection alias used only for reads (local development reuses the `wp` user, which can write, so read-only is enforced by our code and router rather than the database; production would use a read-only user or replica), a router that blocks migrations against it, commands run inside the containers and only db needs to be running.
- Slug changes: our slug follows WordPress's on every run. If a slug changes in WordPress, the old URL stops working; no redirects are kept.
- Two commands are independent; the main app never references auth accounts, so load order doesn't matter.


## 4. Brand API Contract

- Top Review Snippet: Claude recommended a simple "highest rated review" as the top review (because it is simple, deterministic, and easy to document), but this bias towards the brand seems inappropriate for a platform servicing both brands and consumers. I have decided to use the most representative review, determined by the review closest to the brand's mean rating, with tie breaking using "The Price Is Right" rules (closest to mean without going over, so err on the lower rating), then to most recent, then to WordPress ID. Brands with no reviews return `null`. Ties are detected on integer arithmetic (comparing `|rating × count − sum|`) rather than floats, so equal distances compare as equal.
    - Accepted tradeoffs: for a brand with split opinions (all 1s and 5s) the closest review may not represent anyone's actual experience, and the pick may be a bland middle-of-the-road review.
    - With more time: show one positive and one critical review per card.
- Industry Filter Options: Claude requested clarification as to where the filter options are obtained, giving options such as "hard code in to the front end select component" and "derive from the GET response" but as it correctly pointed out, the former makes updates tedious while the latter does not guarantee all five current extant industries are present in the first page of the paginated response, and once filtered, other industries will be excluded from results (and so the options for the select will vanish). I decided instead to add a simple GET endpoint to serve the Industry objects from the django database and use the response to populate the select options. (CHALLENGE.md includes wording suggesting a "single endpoint" but I am taking this to mean in regards to brand listing data, and industries are distinct entities from brand.)
- Industry representation and filtering: Each brand row returns `industries: [{slug, name}]`. Filtering by industry matches brands in any of the requested industries. Filtering is implemented as a subquery (`pk__in=Brand.objects.filter(industries__slug__in=...).values("pk")`) so the outer query never joins industries and we don't inflate aggregates (a brand matching two selected industries would report double its review count for example). `distinct()` considered but rejected; it will remove duplicate rows but not inflated counts.
- Filter, sort, pagination, and errors for `GET /api/brands/`:
    - Filter: `industry=<slug>`, repeatable (matches brands in any of the given industries). An unknown slug returns 400, because industries are a closed, known set.
    - Sort: `ordering=average_rating|-average_rating|review_count|-review_count`. Default is `-average_rating`, with slug as the tie-break.
    - Pagination: `page` and `page_size` (default 12, maximum 50). The response envelope is `{count, next, previous, results}`.
    - Errors: an invalid parameter returns 400 with `{"errors": {"<param>": ["..."]}}`. An out-of-range page returns 404.
- PATCH validation for `short_description`: must be a non-empty string; maximum length 300 characters (after trimming); surrounding whitespace trimmed; HTML treated as plain text.
- Rating display and sorting: the average rating is returned rounded to one decimal place, while sorting uses the unrounded value. Brands with no reviews have a `null` average and sort last regardless of direction. Ties are broken by slug.

## 5. React Component and State

- Cards show one industry badge per industry, sorted by name (the WordPress
  theme showed only the first).
- Industry filter: a single-select `<select>` with an "All industries" option. The API still accepts repeated `industry` values, so the UI can move to multi-select later without an API change.
- URL synchronization:
    - Filter, sort and page live in the query string with the same names as the API; default values are omitted.
    - User changes push a new history entry (`pushState`); `popstate` re-reads the URL.
    - Invalid URL values fall back to defaults instead of erroring.
    - Observable: a deep link reproduces the view, and Back restores the previous filter.
- Pagination: Previous and Next buttons driven by the API's `previous`/`next` links, with a "Page X of Y" label. A button is disabled (not hidden) when there is no page in that direction. After a page change, keyboard focus moves to the results heading so keyboard and screen-reader users land on the new results. Changing the filter or sort resets to page 1. Chosen over numbered page links because there are currently 5 brands (a single page at 12 per page).
- State ownership: the URL owns the user's choices (filter, sort, page); a small `useUrlParams` hook reads and writes them. Fetched data comes from small custom hooks (`useBrands(params)`, `useIndustries()`) using `fetch` with an `AbortController`, so a slow, stale response can never overwrite a newer one. Each hook exposes explicit loading, error, empty and loaded states. `BrandList` owns the hooks and passes values down as props to small presentational children (`IndustryFilter`, `SortSelect`, `BrandCard`, `Pagination`).
    - SWR / TanStack Query: rejected as overkill. Their caching, de-duplication and revalidation don't pay for a dependency with one component and two endpoints. Switching later would only change the inside of `useBrands`.
    - Context provider: rejected. Context solves sharing state across distant parts of a component tree; every consumer here is a direct child of `BrandList`, so props are enough.
    - Redux / Zustand: rejected as overkill for a single component's state.

## 6. SCSS Architecture

- One styling system: the React component reuses the same SCSS classes as the server-rendered pages (`.card`, `.badge`, `.stars`, …). Tailwind (allowed for the React component by CHALLENGE) was rejected because it would mean two styling systems for the same cards and badges.
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
- How the compile step is run (Vite or a `sass` npm script) is part of the deferred frontend-build decision.

## 7. Authentication Service Boundary

- Auth service is responsible for user accounts (login names, active status), credentials, roles/permissions, processing login (checking credentials and active status), token refresh/revocation, and user import. The main app verifies the token through the shared library, never seeing passwords or refresh tokens. Holds the private key that signs tokens and publishes the matching public key. Main app enforces the permission: 401 for an invalid token, 403 for a valid token without permission.
- local token verification vs. calls to auth service: given the scope of the app (traffic is small, reads are public, only one protected endpoint for PATCHing the brand's short description) I have decided on a short-lived access token which the main app verifies locally with an RS256 public key, refreshed with a longer lived refresh token (this will prevent users from having to log in every ~five minutes. This will mean an acceptable demotion window of ~five minutes on the access token however).
- Access Tokens: short-lived RS256 JWTs verified locally. RS256 chosen because with HS256 the same secret signs and verifies, so the main app could mint its own editor tokens. With RS256 only the auth service can sign, and the main app can only verify. Includes claims `sub`, `roles`, `iss`, `aud`, `exp`, `iat`, `jti`. 5-minute access tokens signed RS256. The main app verifies signature, expiry, issuer and audience locally with the public key. An invalid token returns 401. A valid token without permission returns 403.
- Refresh tokens: ~1-day refresh tokens, rotated on every use; used or revoked refresh tokens are blocked. The refresh token carries only the user's identity, never roles. On every refresh the auth service reloads the user from its database: an inactive or deleted user is refused, and the new access token's `roles` come from the user's *current* role assignments.
    - Why this matters: an access token's roles are a snapshot taken when it was issued, and the main app trusts that snapshot until the token expires. Refresh is the only point where a role change reaches a user's tokens, so reloading roles there is what limits the demotion window to one access-token lifetime (~5 minutes).
    - Risk: simplejwt's default refresh copies claims from the old refresh token, and with rotation the stale claims carry forward into each new refresh token. If roles were copied, a demoted editor could keep obtaining editor tokens indefinitely. The implementation overrides this behaviour.
    - Required tests: (1) log in as an editor, demote the user, refresh, and assert the new access token has no editor role and the PATCH returns 403; (2) deactivate a user and assert refresh is refused.
- Public key distribution: the auth service's public key is supplied to the main app at deploy time (a mounted file or environment variable via Compose); the main app never fetches it from the auth service at runtime. The key is therefore always available, and a missing key is a startup configuration error rather than a request-time failure. Tradeoff: rotating the key means redeploying the main app. With more time: publish keys at a JWKS endpoint for easier rotation, which would then require deciding what PATCH returns when keys can't be fetched (503 rather than 401).
- Demotion/revocation/outages: a demoted or deactivated user can act for at most one access-token lifetime (about 5 minutes at most). Accepted given the endpoint's low impact. If the auth service is down, public pages and GET calls are unaffected (because GET endpoints are public). PATCH with a still-valid token works until it expires. Login and refresh will fail however.
- To account for any nefarious editing done by recently demoted editors, I am including a simple audit log that traces who made the edit and what was changed, so such actions can be undone. Revocation only limits what happens after a demotion; edits made while a user legitimately held the editor role can't be prevented, only traced and undone. Every PATCH records the user, token ID, timestamp, and before/after values so edits made before a demotion can be traced and undone if necessary. 
- WordPress `$wp$` hashes (bcrypt over an HMAC-SHA384 prehash) are copied as-is. A custom hasher in the auth service verifies a login by applying the same steps to the submitted password and comparing it with the stored hash. We can test this against known seed data hashes because we know the plain text values of the passwords. Users will not have to change/reset their passwords and log in should be seamless from WordPress. On successful login, Django will re-hash the password with its own algorithm.
- Tradeoffs: security-sensitive code we own (small, needs careful tests including wrong-password rejection, plus a `bcrypt` dependency). Only the `$wp$` format is supported (older WordPress `$P$` hashes would need another hasher, and none are in this data). Users who never log in keep the old hash format.
- Rejected alternatives:
    - unusable passwords set by an admin: nobody can log in until a manual step.
    - one shared known password: an insecure pattern.

## 8. Shared Library
- What's genuinely shared: the token contract (claim names, issuer/audience values, signing algorithm) and role/permission names. The auth service configures token issuance with them. The main app verifies against them. The token contract is defined in one place, so the issuer and verifier can't silently disagree about the token's format.
- Distribution: a local wheelhouse. Releasing the library means bumping the version in its `pyproject.toml` and building a wheel into a `wheels/` directory in the repo. Each service pins an exact version (e.g. `shared-auth==1.2.0`) and installs it with `pip install --find-links wheels/`, so each service upgrades only when its own pin changes. Moving to a real private index later only changes the install flag.
    - Local path / editable install: rejected because both services would always get whatever is on disk, so pinning and staged upgrades can't be shown.
    - Git URL plus tag: rejected because Docker builds would need GitHub access and pushed tags.
    - Private index (e.g. a `pypiserver` container): rejected as extra infrastructure for no benefit at this size.
    - Public PyPI: rejected because it would publish internal auth code publicly.
- Breaking changes ship expand-then-contract, with the verifier always upgrading before the issuer: (1) release v2 whose verifier accepts both old and new token formats; (2) deploy the main app on v2 (nothing changes yet); (3) deploy the auth service on v2, which starts issuing the new format; (4) once all old tokens have expired (refresh lifetime, ~1 day), release v3 without old-format support and roll it out to each service independently.
- Contains core code (claims, permissions, verify) as plain python plus PyJWT, no Django
- DRF classes in a submodule, offered as an optional install. The auth service installs only the core since it does not utilize the library's DRF classes, the main app installs the core plus the DRF classes it will use. `verify_token` and the DRF classes are only used by the main app; CHALLENGE explicitly requires token verification and permission checks in the library. Token signing stays in the auth service.
- Core tests run with pytest alone. the DRF classes are tested with a minimal Django set up inside the test suite, not either service's project.

## 9. Additional Considerations
- DRF in both services: Main app for filtering, ordering, pagination, serializers, PATCH validation. Auth `djangorestframework-simplejwt` for login, refresh rotation and blocking used tokens. One framework and set of conventions across both.
- PostgreSQL, one container per service. `main-db` and `auth-db` postgres containers, each with its own volume and credentials. Tests run against postgres. Decided on postgres because migrations roll back cleanly on failure (MariaDB can't do this) and tests run on the same database as production. A single container for both databases was rejected, as separate containers allows services to fail independently, so "auth database down" can actually be demonstrated. MariaDB was also rejected because it ties us to the system being retired and the above mentioned migrations roll back issue. SQLite was also rejected because tests would run on a different database, and it is weak with concurrent writes. 
- Stored HTML: cleaned at render. Server-rendered pages use Django templates. Brand/review body HTML is stored exactly as in WordPress and cleaned at display time by a single |clean_html template filter using nh3. Only allowlisted tags (p, br, strong, em, a, ul, ol, li, blockquote, h2–h4) and attributes (href on links) survive; event handlers (onclick, onerror…) and style are always removed; links may only use http, https or mailto (so javascript: links are removed). This filter is the only place HTML is marked safe, and tests feed it known XSS payloads. Cleaning at display rather than at import applies however the data got in and keeps the database identical to WordPress.