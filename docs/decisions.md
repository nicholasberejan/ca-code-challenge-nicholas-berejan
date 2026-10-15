# Architecture Decisions

## 1. Schema Modeling

- Reviewers: a content-owned Reviewer model. `Reviewer` is owned by the main app and represents the public persona, not the account. Only WordPress users who authored reviews become Reviewers. `Review` has a FK to `Reviewer`. Queries listing reviews use `select_related("reviewer") to avoid N+1 queries. This model separates the account (credentials, roles, managed by the auth service) from the public persona (main app). Public pages never depend on the auth service.
- Reviewer's have a display_name field, while in the WordPress data the Review also has a reviewer_name field. I believe the intention here is that a review can be created with a reviewer name that might differ from the author `display_name` of the post (like if another user is entering a review on behalf of someone else). However, in the seed data there are no reviews with reviewer_name that differs from their author's display_name. I am going to have the Reviewer's display_name show on all reviews for consistency and forgo the Review's "reviewer_name" field, since the name can be accessed by the Foreign Key to the Reviewer (we will use `select_related` to efficiently include the FK relation when querying reviews.) We could always add a byline to the Review model in the future if we want users to be able to submit reviews on behalf of others.
- Reviewer location: I initially thought the seed data suggested a design flaw wherein the review owned the location, as opposed to the reviewer, however after looking closer I see one brand (SwiftStream, an ISP) being reviewed indicates regional service, so it does make sense that the review would be for that area where it was used, not the Reviewer's current location. I have decided to keep the location on the Review model as a result.
- WordPress allows a brand to have more than one industry, although the seed data has no examples where any brand has more than one industry. I have decided the django app will also support more than one industry for a brand so that this functionality can be included in future updates. We wil make a M2M relation to the Industry model for Brands.
- Average rating: derived, with legacy value retained. A brand's average rating is calculated from its reviews' ratings. The WordPress `average_rating` value is stored as  legacy_average_rating` for audit purposes, and is not returned by the API. This field could be cached and updated on write/import when scaling later.
- Short decription: stored, editable, and seeded on import. `Brand.short_description` is an editable plain-text field, seeded from `post_excerpt` when present, otherwise from ~22 words of `post_content` but stripped of tags with entities decoded. The PATCH ednpoint must edit this field, so it cannot be derived. The trim matches what the WordPress theme displays on cards.

## 2. WordPress Postmeta Strategy

- The source has 10 postmeta rows per brand (not ~30): 4 ACF values, 4 ACF
  field-key references, 2 Yoast fields.
- **First-class fields:** brand `website_url`, `founded_year`,
  `headquarters`, `average_rating` (as `legacy_average_rating`); review
  `rating`, `reviewer_location`; review `brand` becomes an FK.
- **Dropped:** the `_<field>` → `field_…` ACF key references (ACF plumbing);
  review `reviewer_name` (redundant with `Reviewer.display_name`; mismatches
  are reported by the importer).
- **TBD:** Yoast `_yoast_wpseo_title` / `_yoast_wpseo_metadesc`.

## 3. Migration Strategy

- Source: direct reads from WordPress's MariaDB. Import management commands read the WordPress database direcrly with SQL over the DOcker Compose network. This was decided because the MariaDB is the only source containing everything including password hashes and roles, and the WordPress REST API rejected because it can't supply password hashes or roles.
- Two independent commands: main app `import_wordpress` (industries, brands, reviewers, reviews). Auth service `import_wordpress_users` (users, hashes, roles). Each service imports only what it owns. WordPress roles are stored PHP-serialized and parsed with `phpserialize`.
- Re-runnability: imported rows store their WordPress ID, rows are created or updated by that key. Each command runs in a single transaction, a failure leaves nothing half-imported. WordPress-owned fields (title, content, ACF values, industries, reviews) are overwritten on every run, and a brand's industries are replaced to match source. `short_description` is set only when a brand is first created, so editor changes survive re-imports. Later WordPress except changes do not flow thorugh, since this is a one-way cutover that seems right. Removed source entities are rported but not deleted.
- Only published content is migrated.
- Dates come from `post_date_gmt` (UTC)
- Role mapping: administrator becomes editor, subscriber becomes reader, unknown roles become readers.
- Scaling: As brands and reviews grow, implement a batched/chunked reads and use `bulk_create(update_conflicts=True)`

## 4. Brand API Contract

- Top Review Snippet: Claude recommended a simple "highest rated review" as the top review (because it is simple, deterministic, and easy to document), but this bias towards the brand seems inappropriate for a platform servicing both brands and consumers. I have decided to use the most representative review, determined by the review closest to the brand's mean rating, with tie breaking using "The Price Is Right" rules (closest to mean without going over, so err on the lower rating), then to most recent, then to WordPress ID.
- Industry Filter Options: Claude requested clarification as to where the filter options are obtained, giving options such as "hard code in to the front end select component" and "derive from the GET response" but as it correctly pointed out, the former makes updates tedious while the latter does not guarantee all five current extant industries are present in the first page of the paginated response, and once filtered, other industries will be excluded from results (and so the options for the select will vanish). I decided instead to add a simple GET endpoint to serve the Industry objects from the django database and use the response to populate the select options.
- Industry representation and filtering: Each brand row returns `industries: [{slug, name}]`. Filtering by industry matches brands in any of the requested industries. Filtering is implemented as a subquery (`pk__in=Brand.objects.filter(industries__slug__in=...).values("pk")`) so the outer query never joins industries and we don't inflate aggregates (a brand matching two selected industries would report double its review count for example). **TBD** exact filter/sort/pagination/error contracts.

## 5. React Component and State

- Cards show one industry badge per industry, sorted by name (the WordPress
  theme showed only the first).
- **TBD:** filter cardinality in the UI, pagination interaction, URL
  synchronization, state ownership.

## 6. SCSS Architecture

TBD

## 7. Authentication Service Boundary

- Auth service is responsible for user accounts (login names, active status), credentials, roles/permissions, processing login (checking credentials and active status), token refresh/revocation, and user import. The main app verifies the token through the shared library, never seeing passwords or refresh tokens.
- local token verification vs. calls to auth service: given the scope of the app (traffic is small, reads are public, only one protected endpoint for PATCHing the brand's short description) I have decided on a short-lived access token which the main app verifies locally with an RS256 public key, refreshed with a longer lived refresh token (this will prevent users from having to log in every ~five minutes, an acceptable demotion window)
- to account for any nefarious editing done by recently demoted editors, I am including a simple audit log that traces who made the edit and what was changed, so such actions can be undone.
- passwords will carry over from WordPress, and a hasher built and included in the auth service. We can test this against known seed data hashes because we know the plain text values of the passwords. Users will not have to change/reset their passwords and log in should be seamless from WordPress. Once logged in, Django will re-hashes the password with it's own algorithm.

## 8. Shared Library

- Contains core code (claims, permissions, verify) as plain python plus PyJWT, no Django
- DRF classes in a submodule, offered as an optional install. The auth service installs only the core since it does not utilize the library's DRF classes, the main app installs the core plus the DRF classes it will use.
