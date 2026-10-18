# Brand Reviews: WordPress → Django

A Django replacement for a small WordPress consumer-reviews site (brands, reviews, industries), built for the challenge in [`CHALLENGE.md`](CHALLENGE.md). It contains:

- a **main Django app**: public pages, a brand listing API and a protected brand edit;
- a **React `<BrandList />`** and the theme rebuilt as **SCSS**;
- a separate **auth Django service**: accounts, roles and RS256 tokens;
- a **shared Python library** (`shared-auth`) with the token contract and verification code;
- **import commands** that migrate content and users from the WordPress database.

Design rationale lives in [`docs/decisions.md`](docs/decisions.md), the required behaviour in [`docs/acceptance-criteria.md`](docs/acceptance-criteria.md), and notes on the AI-assisted process in [`docs/development-log.md`](docs/development-log.md).

## Quick start

Only Docker is required on the host.

```bash
cp .env.example .env
docker compose up -d          # or: make up. The first run builds the images (a few minutes).
make import                   # migrate WordPress content (web) and users (auth)
```

`make` is a convenience; every target is a `docker compose` command (see `Makefile`).

| URL | What |
|---|---|
| <http://localhost:8000/> | The Django site (homepage, `/brand/`, `/brand/<slug>/`, `/review/<slug>/`) |
| <http://localhost:8000/api/brands/> | Brand listing API |
| <http://localhost:8001/admin/> | Auth service admin (`admin` / `admin` after `make import`) |
| <http://localhost:8080/> | The original WordPress site (the migration source) |
| <http://localhost:8081/> | phpMyAdmin for the WordPress database |

Seed logins after `make import`: `admin` / `admin` (editor) and the eight reviewers, e.g. `sarah_k` / `changeme` (reader). These are the WordPress seed passwords; `.env.example` holds development-only settings, including a **development-only** RS256 key pair.

## Architecture

```
                 WordPress MariaDB (db)  ── migration source only, read-only session
                    │                 │
     import_wordpress│                 │import_wordpress_users
                    ▼                 ▼
 browser ──► web :8000 (Django)     auth :8001 (Django)  ◄── login / refresh / logout
             pages, /api/brands/,   accounts, roles,
             PATCH (editors)        RS256 signing (private key)
                │                       │
             main-db (PostgreSQL)    auth-db (PostgreSQL)

 web verifies access tokens locally with the public key (shared-auth); it never
 calls auth, never sees passwords or refresh tokens, and stores no users.
```

| Path | What |
|---|---|
| `services/web/` | Main Django app: `content` app (models, importer, sanitizer, queries, API, pages) |
| `services/auth/` | Auth Django service: `accounts` app (user model, WordPress hasher, tokens, import, admin) |
| `packages/shared-auth/` | Shared library: token contract, `verify_token`, optional DRF classes |
| `wheels/` | Released `shared-auth` wheels; each service pins an exact version |
| `frontend/` | React + TypeScript (`src/`) and SCSS (`scss/`), built by Vite into the `web` image |
| `scripts/` | Verification scripts, the end-to-end check, release helpers |

Each service has its own PostgreSQL container and credentials. `web` does not depend on `auth` (or on WordPress) to start, so public pages keep working while either is down.

## Using the site and API

| Route | Content |
|---|---|
| `/` | Hero and the 6 most recent reviews |
| `/brand/` | `<BrandList />`: industry filter, sort, pagination, all in the URL |
| `/brand/<slug>/` | Brand: industries, average of its reviews, website, founded, headquarters, description, all reviews |
| `/review/<slug>/` | Review: brand link, rating, reviewer and location, date, body |
| `GET /api/brands/` | Paginated brand cards |
| `GET /api/industries/` | Every industry, `[{"slug", "name"}]`, for the filter |
| `PATCH /api/brands/<slug>/` | Edit `short_description` (editors only, see below) |

`GET /api/brands/`:

- `industry=<slug>`, repeatable: brands in **any** of the given industries.
- `ordering`: `-average_rating` (default), `average_rating`, `-review_count`, `review_count`. Ties are broken by slug. Brands with no reviews have a `null` average and sort last in either rating direction.
- `page` and `page_size` (default 12, maximum 50); the response is `{count, next, previous, results}`.
- Each result: `name`, `slug`, `industries` (`[{slug, name}]`), `average_rating` (derived from the reviews, 2 decimals), `review_count`, `short_description` and `top_review` (`{slug, title, rating, reviewer_name, snippet}` or `null`). The top review is the one whose rating is closest to the brand's average; on an exact tie the lower rating wins, then the newest review, then the lowest WordPress ID.
- An invalid parameter returns `400` with `{"errors": {"<param>": ["..."]}}` (every invalid parameter at once); a page past the end returns `404`. Every API error uses this shape.

```bash
curl 'http://localhost:8000/api/brands/?industry=insurance&industry=telecom&ordering=-review_count'
```

## Authentication and editing

The auth service owns accounts, passwords and roles (`reader`, `editor`). Access tokens last 5 minutes and refresh tokens 1 day. The main app checks access tokens itself with the public key.

```bash
# Log in
TOKENS=$(curl -s -X POST localhost:8001/api/token/ -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "admin"}')
ACCESS=$(echo "$TOKENS" | sed -E 's/.*"access":"([^"]+)".*/\1/')
REFRESH=$(echo "$TOKENS" | sed -E 's/.*"refresh":"([^"]+)".*/\1/')

# Edit a brand's short description (editor role required)
curl -s -X PATCH localhost:8000/api/brands/acme-insurance/ \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"short_description": "Hartford-based insurer."}'

# Refresh: a new pair; the old refresh token is used up
curl -s -X POST localhost:8001/api/token/refresh/ -H 'Content-Type: application/json' \
  -d "{\"refresh\": \"$REFRESH\"}"

# Log out: that refresh token can no longer be used
curl -s -X POST localhost:8001/api/token/logout/ -H 'Content-Type: application/json' \
  -d "{\"refresh\": \"$REFRESH\"}"
```

- **PATCH** accepts only `short_description`: trimmed, 1–300 characters, stored as plain text. It returns the brand in the listing format. No or an invalid token: `401`; a valid token without the `editor` role (e.g. `sarah_k`): `403`; any other field: `400`.
- **Tokens:** access tokens carry `sub`, `roles`, `iss`, `aud`, `exp`, `iat`, `jti` (plus `token_type`). Refresh tokens carry no roles. Each refresh reloads the user's current roles, refuses inactive users, and issues a new pair.
- **Accepted staleness:** a role change, deactivation or logout takes effect at the next refresh. An access token already issued keeps working, with its roles, until it expires: at most 5 minutes. Revocation is not immediate.
- **Operators** change roles (groups), deactivate users and revoke all of a user's sessions in the admin at <http://localhost:8001/admin/>.
- **If the auth service is down,** public pages and GET APIs are unaffected, and PATCH keeps working with an unexpired access token; logging in and refreshing fail. To see it: log in as above, `docker compose stop auth`, repeat the PATCH, then `docker compose start auth`.
- **If WordPress is down** (after the import), everything above still works; only the import commands need it.

## Migrating WordPress data

```bash
make import
# runs, for each service, its migrations and then:
docker compose run --rm web  python manage.py import_wordpress         # content
docker compose run --rm auth python manage.py import_wordpress_users   # users
```

Both commands read the WordPress MariaDB directly over the Compose network (`WP_DB_*` in `.env`), through a read-only database session. They only need WordPress while they run, they are independent, and each runs in one transaction: a failure saves nothing. Each prints a summary of what it created, updated, kept and found missing.

**Content (`import_wordpress`).** Imports published industries, brands, reviewers and reviews. Re-running is safe:

- Rows are matched by **WordPress ID, not slug**, so a slug changed in WordPress updates the existing row; the old URL is not redirected.
- **WordPress-owned fields** (titles, content, slugs, ACF values, ratings, industries, authors) are updated when they change; unchanged rows are not written. A second run against unchanged data creates and updates nothing.
- **`short_description` belongs to Django:** it is seeded when a brand is first imported (excerpt, or the first 22 words of the content) and never overwritten, so editors' changes survive.
- **Missing content:** content that disappeared from WordPress is reported and kept. `--prune` deletes it: missing reviews, missing brands with their reviews, missing industries, and reviewers left with no reviews.
- **Reported, not stored:** reviews whose brand isn't imported, `reviewer_name` values that differ from the author, unrecognised postmeta keys, and non-`http(s)` website URLs.
- **Sanitized at import:** brand and review HTML passes through one allowlist sanitizer (`p`, `br`, `strong`, `em`, `a[href]` with `http`/`https`/`mailto`, `ul`, `ol`, `li`, `blockquote`, `h2`–`h4`) before it is stored.

**Users (`import_wordpress_users`).** Creates an account per WordPress user. The WordPress username becomes the username, and the email and password hash are copied. WordPress `administrator` becomes `editor` with admin access; every other role becomes `reader`. It **only creates**: an existing account is never modified, so a re-run cannot undo a demotion, a deactivation or a password upgrade. Users missing from WordPress are reported, never deleted. Passwords keep working: the WordPress 6.8+ `$wp$` hashes are checked by a transitional hasher that mirrors WordPress's own `wp_check_password`, and Django re-hashes each password on that user's first successful login.

## Modeling decisions (summary)

Full rationale and rejected alternatives: [`docs/decisions.md`](docs/decisions.md).

- **Source identity:** each imported row keeps its WordPress ID in a unique column; slugs are only public URLs.
- **Reviewer** is the main app's record of a review author's public name, not an account. Accounts, passwords and roles live only in the auth service. `reviewer_location` stays on each review: the same person reviews services in different places.
- **Average rating:** calculated from the reviews. WordPress's stored `average_rating` contradicts the reviews for 4 of the 5 brands, so it is kept as `legacy_average_rating` for audit only and never shown, sorted on or returned.
- **Industries** are many-to-many. The filter uses a subquery, so a brand matching two selected industries appears once and its review count isn't doubled.
- **Postmeta:** ACF values became typed columns; ACF field references and Yoast SEO copy are dropped; nothing is stored as JSON; unknown keys are reported.
- **HTML** is sanitized once, at import, where WordPress content enters the system.

## Frontend and SCSS

`<BrandList />` (`frontend/src/`) keeps its state in the URL, with the API's parameter names (`?industry=insurance&ordering=-review_count&page=2`), so links can be shared and Back/Forward work. It fetches with plain `fetch` + `AbortController`, without a state library. Older responses can never replace newer ones. It has explicit loading, empty and error (with Retry) states, an `aria-busy` refresh, a live-region result count, and focus moved to the results after a page change.

The SCSS (`frontend/scss/`) rebuilds `reference/theme.css`:

- **Partials:** `abstracts/` (tokens, breakpoint mixin), `base/`, `layout/`, `components/`, `pages/`; `main.scss` only composes them.
- **Tokens:** every design value is defined once in `_tokens.scss` and emitted as CSS custom properties. Most of the theme's own names are kept (`--color-primary`, `--shadow-sm`, …); the four that changed (`--color-card`, `--radius`, `--shadow`, `--max-width`) are emitted as aliases.
- **Lint rules:** Stylelint enforces `@use` (no `@import`), BEM class names, nesting depth 2, media queries only through the mixin, and no element selectors in components.
- **One styling system:** the Django templates and React use the same classes.

Both are built by Vite inside the `web` image. To work on them:

```bash
docker compose run --rm frontend npm run test                    # Vitest
docker compose run --rm frontend npm run build                   # compile SCSS + bundle into frontend/dist
docker compose run --rm --service-ports frontend npm run dev     # Vite dev server on :5173, /api proxied to web
docker compose build web                                         # serve frontend changes from Django
```

## Shared library

`packages/shared-auth/` holds what both services must agree on:

- **The token contract:** algorithm, claim names, roles and permissions. The auth service issues tokens with it and the main app verifies against it.
- **`verify_token`** and optional DRF authentication/permission classes, which the main app uses.

Signing stays in the auth service. The core has no Django dependency. [`packages/shared-auth/README.md`](packages/shared-auth/README.md) explains each module.

```bash
docker compose run --rm shared-auth uv run --locked pytest   # its tests, without either Django project
make lib-release   # build wheels/shared_auth-<version>-py3-none-any.whl (bump the version first)
make lock          # re-resolve a service's lockfile after changing its pin
```

Released wheels in `wheels/` are immutable. Each service pins an exact version and installs it from the wheelhouse: web `shared-auth[drf]==0.2.0`, auth `shared-auth==0.2.0`. That lets one service upgrade before the other. **Breaking changes ship expand-then-contract**, verifier before issuer:

1. Release a version whose verifier accepts both the old and the new format.
2. Deploy web on it.
3. Deploy auth on it; it starts issuing the new format.
4. After the refresh lifetime (1 day), release a version without the old format and move each service to it when convenient.

## Verification

```bash
make hooks         # once per clone: every git commit then runs verify-fast
make verify-fast   # ruff, strict mypy (shared-auth), shared-auth tests, tsc, ESLint (jsx-a11y),
                   # Prettier, Stylelint, Vitest. No databases.
make verify        # everything: the above + both Django suites on PostgreSQL, Django and
                   # migration checks, both import idempotency checks, the end-to-end flow,
                   # the production frontend build
```

Run `make verify` before calling work complete. Everything runs in containers. It imports the seed data into the dev databases, and its end-to-end check (`scripts/e2e/auth_flow.py`) exercises the running services:

- login and PATCH as editor and reader;
- demotion taking effect at refresh;
- refresh replay, deactivation and logout;
- an auth-service outage and a WordPress outage (it stops and restarts those containers);
- an edit surviving `import_wordpress`.

It uses its own test users and restores the brand it edits.

## What would change with more time or at scale

The current choices fit a five-brand, single-team assessment; these are the next steps when there is a reason for them:

- **Pagination:** cursor pagination (and a versioned `/api/v1/`) for a mobile client or a large, changing dataset.
- **Aggregates:** stored or cached averages and top reviews, updated on import, once measurement shows the per-request calculation matters.
- **Migration:** batched reads and `bulk_create(update_conflicts=True)` at 100× the data, a read-only WordPress database user or a replica, and a `--dry-run` for `--prune`.
- **Keys and revocation:** a JWKS endpoint for key rotation, and token introspection or a per-user token version if immediate revocation became a requirement.
- **Login hardening:** rate limiting / lockout on `POST /api/token/` (none today; acceptable for a local assessment, not for a public deployment).
- **Operations:** gunicorn/uvicorn instead of the development server, `collectstatic` with hashed static files, CI running `make verify`, structured logging and an audit trail of edits.
- **Frontend workflow:** `vite build --watch` wired into Django for frontend work without rebuilding the image.

## AI defaults kept over my own preference

This project was built with Claude Code ([`docs/development-log.md`](docs/development-log.md) records where AI output was corrected or rejected). These are the places where I started with a different preference and kept the AI's recommendation:

- **Shared-library distribution:** I first assumed publishing to PyPI. I kept the AI's local wheelhouse with exact pins, because PyPI would publish internal auth code and a wheelhouse still demonstrates versioned, staged upgrades.
- **BrandList state:** I have used context providers and SWR before. I kept the AI's plain hooks with `fetch` and `AbortController`: with one component and two endpoints, a library or context added nothing.
- **`--prune` stays opt-in:** I asked whether pruning should be the default, since the final cutover runs it. I kept it opt-in: a bad source or connection would otherwise delete editor-owned data on a routine run.
- **The loading message stays inline:** I proposed extracting a `LoadingIndicator` along with the results and error components. I kept the AI's suggestion to extract only the two with a real contract (`BrandResults`, `LoadError`).

## The WordPress source environment

The original challenge environment is unchanged. WordPress 6.9 with ACF and Yoast runs at :8080 on MariaDB (`db`, auto-imported from `db/dump.sql` on first boot), with phpMyAdmin at :8081 and `wpcli` under the `tools` profile. The seed is 5 brands, 60 reviews by 8 reviewers, 5 industries, and Home/About/Contact pages. The `brand`/`review` post types and ACF fields are defined in `wp-content/mu-plugins/`; the theme is in `wp-content/themes/consumer-reviews/`.

```
make up | down | status | logs        # start (everything) / stop / list / tail WordPress logs
make reset                            # stop and wipe ALL volumes, including the Django databases
make wp ARGS="plugin list"            # run wp-cli
make bootstrap && make dump           # re-seed WordPress and export db/dump.sql (after `make reset && make up`)
```

The site URL is hard-coded as `http://localhost:8080` in the dump. ACF and Yoast are committed under `wp-content/plugins/` so no internet access is needed on first boot.
