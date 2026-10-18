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

The replacement site is being built in phases. What exists today is the foundation: both Django services, their databases, the shared library, the frontend toolchain, and verification. Brands, reviews, the API, pages, login and the WordPress import are not implemented yet.

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
make verify        # everything: + Django tests on PostgreSQL, Django checks, production build
make test          # every test suite
```

The commit hook is quiet: one line per check, plus the output of any check that fails. For full output, run `VERIFY_VERBOSE=1 git commit ...`.

All checks run in containers. `make verify` lists checks that are deferred until their feature exists (currently: WordPress import idempotency); deferred checks are reported, never counted as passed.

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

Released versions are immutable: bump `version` in `packages/shared-auth/pyproject.toml` before `make lib-release`. Each service pins an exact version (`shared-auth==0.1.0` in its `pyproject.toml`) and upgrades on its own schedule. See `packages/shared-auth/README.md`.

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
make import     # import WordPress content into the main app (see "Migrating WordPress data")
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

> **Not implemented yet:** the auth service's `import_wordpress_users` (users, password hashes, roles). `make import` will run both commands once it exists.
