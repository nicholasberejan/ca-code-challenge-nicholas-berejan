# Brand Reviews WordPress (Interview Challenge Source)

Self-contained, reproducible WordPress site used as the source for a WP → Django migration challenge.

The site is a small consumer-reviews directory: **brands** with profile pages plus user-submitted **reviews** linked to each brand. Two custom post types, one taxonomy, ACF fields, Yoast SEO metadata.

## Quick start

Only Docker is required on the host.

```bash
cp .env.example .env
make up            # or: docker compose up -d
```

The first `up` builds the Django images (including the frontend production build), so it takes a few minutes. After that:

- Public site: <http://localhost:8080>
- WP admin:    <http://localhost:8080/wp-admin> (`admin` / `admin`)
- phpMyAdmin:  <http://localhost:8081>
- REST root:   <http://localhost:8080/wp-json/wp/v2/>
- Django web service:  <http://localhost:8000/healthz>
- Django auth service: <http://localhost:8001/healthz>

The DB is auto-imported from `db/dump.sql` on first boot. No manual setup required for candidates.

## Development (Django replacement site)

The replacement site: the main Django app (public pages, brand API, protected brand editing), the auth service (accounts, roles, tokens), the shared library, the React `<BrandList />` and the SCSS theme, plus the WordPress imports for content and users. See "Public pages and API", "Authentication and editing" and "Migrating WordPress data" below.

| Path | What it is |
|---|---|
| `services/web/` | Main Django app (port 8000), database `main-db` |
| `services/auth/` | Auth Django service (port 8001), database `auth-db` |
| `packages/shared-auth/` | Shared Python library, installed into both services from `wheels/` |
| `wheels/` | Local wheelhouse of released `shared-auth` versions |
| `frontend/` | React + TypeScript (`src/`) and SCSS (`scss/`), built with Vite |

### Configuration

`.env.example` holds every setting, including a development-only RS256 key pair (**DEV ONLY — production keys come from a secret store**). Compose passes the private key only to `auth`; `web` receives only the public key. If you created `.env` before these settings existed, copy `.env.example` to `.env` again.

Both Django services run migrations on start and serve with Django's development server; their source directories are bind-mounted, so code changes reload automatically. Dependency changes need an image rebuild: `docker compose build`.

### Verification

```bash
make hooks         # once per clone: every git commit then runs verify-fast
make verify-fast   # lint, format, types, unit tests (no databases)
make verify        # everything: + Django tests on PostgreSQL, Django checks, both import
                   # idempotency checks, the end-to-end token flow, production build
make test          # every test suite
```

The commit hook is quiet: one line per check, plus the output of any check that fails. For full output, run `VERIFY_VERBOSE=1 git commit ...`.

All checks run in containers. The end-to-end check (`scripts/e2e/auth_flow.py`) runs against the running `web` and `auth` services: login, PATCH as editor and reader, demotion taking effect at refresh, refresh replay, deactivation, logout, an auth-service outage (it stops and restarts `auth`), and an edit surviving `import_wordpress`. It uses its own test users and restores the brand it edits. Checks whose feature does not exist yet would be listed as deferred, never counted as passed; currently there are none.

### Frontend and SCSS

`frontend/` holds the React + TypeScript `<BrandList />` (`src/`) and the site's SCSS (`scss/`), both built by Vite. The production build (`brand-list.js` and `main.css`) runs inside the `web` image build, and Django serves it under `/static/frontend/`: every server-rendered page loads `main.css`, and `/brand/` mounts `<BrandList />` into `<div id="brand-list">`.

`<BrandList />` reads `GET /api/industries/` for its filter options and `GET /api/brands/` for results. Filter, sort and page live in the URL (`?industry=insurance&ordering=-review_count&page=2`, same names as the API, defaults omitted), so links can be shared and Back/Forward work.

The SCSS is the WordPress theme (`reference/theme.css`) rebuilt as `abstracts/` (tokens, breakpoint mixin), `base/`, `layout/`, `components/` and `pages/` partials; `main.scss` only composes them. Every design value is defined once in `abstracts/_tokens.scss` and emitted as a CSS custom property; Stylelint enforces `@use`, BEM class names, nesting depth 2, media queries through the mixin, and no element selectors in components.

On-demand frontend container (the `tools` profile):

```bash
docker compose run --rm frontend npm run test       # Vitest
docker compose run --rm frontend npm run build      # compile SCSS + bundle into frontend/dist
docker compose run --rm --service-ports frontend npm run dev   # Vite dev server on :5173, /api proxied to web
docker compose build web                            # serve frontend changes from Django
```

### Shared library

```bash
docker compose run --rm shared-auth uv run --locked pytest   # its tests, without either Django project
make lib-release   # build wheels/shared_auth-<version>-py3-none-any.whl
make lock          # re-resolve the services' lockfiles after changing their shared-auth pin
```

Released versions are immutable: bump `version` in `packages/shared-auth/pyproject.toml` before `make lib-release`. Each service pins an exact version (currently `shared-auth==0.2.0` in its `pyproject.toml`) and upgrades on its own schedule. See `packages/shared-auth/README.md`.

**Breaking changes ship expand-then-contract** (the verifier always upgrades before the issuer), so the two services never have to deploy at the same moment:

1. Release a version whose verifier accepts both the old and the new token format.
2. Deploy the web service (the verifier) on it. Nothing changes yet.
3. Deploy the auth service (the issuer) on it; it starts issuing the new format.
4. Once every old token has expired (the refresh lifetime, 1 day), release a version without the old format and move each service to it when convenient.

## Stack

| Service     | Image                            | Port  | Purpose                                |
|-------------|----------------------------------|-------|----------------------------------------|
| `db`        | `mariadb:11`                     | -     | Database; auto-imports `db/dump.sql`   |
| `wordpress` | `wordpress:6.9-php8.3-apache`    | 8080  | WP + Apache + PHP                      |
| `wpcli`     | `wordpress:cli-php8.3`           | -     | Helper for re-seeding / dumping        |
| `phpmyadmin`| `phpmyadmin:5`                   | 8081  | Optional DB browser                    |

## What's committed

```
docker-compose.yml          # the stack
.env.example                # config defaults
Makefile                    # make targets
db/dump.sql                 # seeded database snapshot
scripts/seed.sh             # bootstrap script (install + plugins + seed)
wp-content/plugins/         # WP default plugins + ACF + Yoast (committed for offline reproducibility)
wp-content/mu-plugins/
  cpt.php                   # registers `brand` and `review` CPTs and `industry` taxonomy
  acf-fields.php            # registers ACF field groups in code
wp-content/themes/
  consumer-reviews/         # custom theme used by the site
```

WP core files and the default themes (e.g. twentytwentyfour) live inside the `wp_files` named volume and are recreated from the image on first boot. Only the custom `consumer-reviews` theme is committed to the repo.

## Make targets

```
make up         # start everything: WordPress source + Django services + databases
make down       # stop containers (keeps volumes)
make reset      # stop AND wipe all volumes, including the Django databases (next 'up' re-imports dump.sql)
make logs       # tail wordpress + db
make wp ARGS="plugin list"   # run wp-cli inside the stack
make bootstrap  # full re-seed: WP core install + plugin install + content seed
make dump       # export the current DB to db/dump.sql
make status     # show running services
make import     # import WordPress content and users (see "Migrating WordPress data")
make hooks      # enable git hooks (once per clone)
make verify-fast / make verify / make test   # see "Verification" above
make lib-release / make lock                 # see "Shared library" above
```

## Rebuilding the dump from scratch

If you change the schema or seed data:

```bash
make reset
make up
make bootstrap
make dump
git add db/dump.sql wp-content/plugins
git commit -m "Refresh seed data"
```

`make bootstrap` is idempotent enough to re-run, but the cleanest path is reset → up → bootstrap → dump.

## Content model

**`brand` CPT** at `/brand/<slug>/`
- Standard fields: title, content (body), featured image (optional)
- ACF fields: `website_url`, `founded_year`, `headquarters`, `average_rating`
- Taxonomy: `industry`
- Yoast: `_yoast_wpseo_title`, `_yoast_wpseo_metadesc` in postmeta

**`review` CPT** at `/review/<slug>/`
- Standard fields: title, content (review body), post_author (mapped to a real WP user)
- ACF fields: `rating` (1-5), `reviewer_name`, `reviewer_location`, `brand` (post object → brand id)

Seeded volume: 5 brands (one per industry), 60 reviews (12 per brand) authored by 8 reviewer users, 3 static pages (Home/About/Contact), 1 admin user.

## Theme

The active theme is a custom one at `wp-content/themes/consumer-reviews/` (committed to the repo). It renders:

- Homepage with featured brands and recent reviews
- Brand archive (`/brand/`) — card grid
- Single brand page (`/brand/<slug>/`) — hero with industry badge, star rating, website / founded / HQ metadata, body content, and full list of customer reviews
- Review archive (`/review/`) — paginated list
- Single review (`/review/<slug>/`) — back-link to brand, star rating, reviewer name/location, body
- Page template for About / Contact / Home pages

The theme is intentionally small (~10 PHP files + one stylesheet) and is meant to show candidates what the data renders as. They are not expected to clone the theme — just to migrate the underlying data.

## Endpoints worth knowing

- `/wp-json/wp/v2/brands` — list brands (note: `rest_base` is `brands` even though post type is `brand`)
- `/wp-json/wp/v2/brands/<id>` — single brand with ACF fields under `acf`
- `/wp-json/wp/v2/reviews` — list reviews
- `/wp-json/wp/v2/industry` — taxonomy terms
- `/wp-json/wp/v2/users` — reviewer users
- `/wp-json/wp/v2/pages` — static pages

ACF fields are exposed natively via `show_in_rest: true` set in `wp-content/mu-plugins/acf-fields.php`.

## Notes for the maintainer

- The `wp-content/plugins/advanced-custom-fields/` and `wp-content/plugins/wordpress-seo/` plugin code is GPL and committed to the repo so candidates don't need internet on first boot.
- `wp-content/plugins/akismet/` and `hello.php` are WP defaults — left in place but inactive.
- The site URL is hardcoded as `http://localhost:8080` in the dump (in `wp_options.siteurl` and `home`). Changing the port requires a search/replace in `db/dump.sql` before commit, or just override via `WP_HOME` / `WP_SITEURL` constants.
- `_yoast_wpseo_*` postmeta is seeded for brand posts only.

## Public pages and API (main app, port 8000)

All of these are public and work without the auth service.

| Route | Content |
|---|---|
| `/` | Hero and the 6 most recent reviews |
| `/brand/` | Brand listing: the React `<BrandList />` (industry filter, sort, pagination), fed by the two APIs below |
| `/brand/<slug>/` | Brand: industries, rating from its reviews, website, founded, headquarters, description, all reviews |
| `/review/<slug>/` | Review: brand link, rating, reviewer, location, date, body |
| `GET /api/brands/` | Paginated brand cards (below) |
| `GET /api/industries/` | Every industry as `[{"slug", "name"}]`, for filter options |

`GET /api/brands/` parameters:

- `industry=<slug>`: repeatable; returns brands in **any** of the given industries.
- `ordering`: `-average_rating` (default), `average_rating`, `-review_count`, `review_count`. Ties are broken by slug. With either `average_rating` ordering, brands with no reviews (average `null`) sort last.
- `page` (default 1) and `page_size` (default 12, maximum 50).

```bash
curl 'http://localhost:8000/api/brands/?industry=insurance&industry=telecom&ordering=-review_count&page_size=5'
```

Each result has `name`, `slug`, `industries` (`[{slug, name}]`), `average_rating` (derived from the reviews, a number rounded to 2 decimals, `null` without reviews), `review_count`, `short_description` and `top_review` (`{slug, title, rating, reviewer_name, snippet}` or `null`). The envelope is `{count, next, previous, results}`.

The top review is the one whose rating is closest to the brand's average; on an exact tie the lower rating wins, then the newest, then the lowest WordPress ID.

Errors: an invalid parameter returns `400` with `{"errors": {"<param>": ["..."]}}` (all invalid parameters at once); a page past the end returns `404` with the same shape.

## Authentication and editing (auth service, port 8001)

The auth service owns accounts, passwords and roles (`reader`, `editor`) and issues RS256 tokens. The main app checks tokens itself with the auth service's public key: it never calls the auth service and stores no users.

```bash
# Log in: a 5-minute access token and a 1-day refresh token
TOKENS=$(curl -s -X POST localhost:8001/api/token/ -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "admin"}')
ACCESS=$(echo "$TOKENS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access"])')
REFRESH=$(echo "$TOKENS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["refresh"])')

# Edit a brand's short description (editors only)
curl -s -X PATCH localhost:8000/api/brands/acme-insurance/ \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"short_description": "Hartford-based insurer."}'

# New token pair; the old refresh token is used up
curl -s -X POST localhost:8001/api/token/refresh/ -H 'Content-Type: application/json' \
  -d "{\"refresh\": \"$REFRESH\"}"

# Log out: that refresh token can no longer be used
curl -s -X POST localhost:8001/api/token/logout/ -H 'Content-Type: application/json' \
  -d "{\"refresh\": \"$REFRESH\"}"
```

- `PATCH /api/brands/<slug>/` accepts only `short_description` (trimmed, 1–300 characters, plain text) and returns the brand in the listing format. No or an invalid token: `401`. A valid token without the `editor` role: `403`. Any other field: `400`.
- Access tokens carry `sub`, `roles`, `iss`, `aud`, `exp`, `iat`, `jti`. Refresh tokens carry no roles: each refresh reloads the user's current roles, refuses inactive users, and issues a new pair.
- **Accepted staleness:** a role change or deactivation takes effect at the next refresh, so an access token already issued keeps its roles for at most 5 minutes. Logout and session revocation stop refresh tokens, not issued access tokens.
- Operators change roles (groups), deactivate users and revoke all of a user's sessions ("Revoke all sessions" action) in the Django admin at <http://localhost:8001/admin/>.
- **If the auth service is down:** public pages and GET APIs are unaffected, and PATCH keeps working with an unexpired access token; logging in and refreshing fail.

The token contract (algorithm, claim names, roles, permissions) and the verification code live in the shared library, released as `wheels/shared_auth-0.2.0-py3-none-any.whl`: the web service pins `shared-auth[drf]==0.2.0`, the auth service `shared-auth==0.2.0`.

## Migrating WordPress data into Django

The main app's `import_wordpress` command copies published WordPress content (industries, brands, reviewers, reviews) into the `web` service's PostgreSQL database. It reads the WordPress MariaDB (`db` service) directly over the Compose network, using `WP_DB_HOST`, `WP_DB_NAME`, `WP_DB_USER` and `WP_DB_PASSWORD` from `.env`. The WordPress database is needed only while the command runs; the `web` service starts without it.

```bash
docker compose up -d db web                                      # WordPress source + main app
make import                                                       # = the command below
docker compose exec web python manage.py import_wordpress         # import / re-import
docker compose exec web python manage.py import_wordpress --prune # also delete what WordPress no longer has
```

The command prints a summary of created / updated / unchanged / missing rows per entity, plus any reviews it skipped, reviewer-name mismatches, website URLs it did not store (only `http(s)` URLs are kept, because they are rendered as links) and unrecognised postmeta keys.

**Re-running is safe.**

- Rows are matched by their WordPress ID, never by slug. A slug changed in WordPress updates the existing row (the old URL stops working; there are no redirects).
- WordPress-owned fields (titles, content, slugs, ACF values, ratings, industries, authors) are overwritten when they differ. Unchanged rows are not written, so a second run against unchanged WordPress data reports nothing created or updated.
- `short_description` is set only when a brand is first imported (from the excerpt, or the first 22 words of the content). After that it belongs to Django: re-imports never overwrite it.
- Each run is one transaction: if anything fails, nothing from that run is saved.
- Content that exists in Django but no longer in WordPress is reported and kept. `--prune` deletes it: missing reviews, missing brands with their reviews, missing industries, and reviewers left with no reviews. A review whose brand is no longer imported (unpublished or deleted) is skipped and counts as missing: like other missing rows, its existing copy is kept unchanged (on its previous brand) and reported until `--prune` deletes it.
- If WordPress gives a slug to a new post while the row that held it is missing (and kept), the import stops with a message naming both posts; re-run with `--prune` to delete the missing row.
- Only published content is imported; dates come from `post_date_gmt` (UTC).

**HTML is sanitized at import.** Brand and review bodies are stored only after passing through one allowlist sanitizer (`content/sanitize.py`): `p`, `br`, `strong`, `em`, `a` (`href` only; `http`, `https`, `mailto`), `ul`, `ol`, `li`, `blockquote`, `h2`–`h4`. Scripts, event handlers, styles and `javascript:` links never reach the database.

**WordPress is never written.** The `wordpress` connection is opened as a read-only session, so writes are rejected even though the local `wp` database user could write, and a database router keeps migrations and models off it. In production, use a read-only database user or a replica.

**Scaling.** At 100x the data, the plan is batched reads and `bulk_create(update_conflicts=True)` instead of per-row writes; at the current size, straightforward per-row upserts are clearer.

### Users (auth service)

```bash
docker compose exec auth python manage.py import_wordpress_users   # also run by `make import`
```

Creates an auth account for every WordPress user: `user_login` becomes the username, plus the email and the WordPress password hash. WordPress `administrator` becomes the `editor` role with access to the auth service's Django admin; `subscriber` and any other role become `reader`.

The user import **only creates**. An account that already exists (matched by WordPress user ID) is never modified, because after cutover the auth service owns roles, passwords and active status: a re-run cannot undo a demotion, a deactivation or an upgraded password. Users missing from WordPress are reported, never deleted.

**Passwords.** Users keep their WordPress passwords. The WordPress 6.8+ `$wp$` hashes are copied as-is and checked by a transitional hasher (`accounts/hashers.py`, mirroring WordPress's `wp_check_password`); on the first successful login Django re-hashes the password with its own hasher. Seed logins: `admin` / `admin` (editor), every other user / `changeme` (reader).

The two imports are independent and can run in either order.
