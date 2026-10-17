SHELL := /bin/bash
COMPOSE := docker compose
WPCLI := $(COMPOSE) run --rm wpcli

.PHONY: help up down restart logs reset wp bootstrap dump status \
	hooks test verify-fast verify lib-release lock

help:
	@echo "Targets:"
	@echo "  up              Start everything: WordPress source + Django services + databases"
	@echo "  down            Stop containers (preserve data)"
	@echo "  reset           Stop containers AND wipe all volumes (full cold start on next 'up')"
	@echo "  logs            Tail wordpress + db logs"
	@echo "  wp ARGS=\"...\" Run wp-cli inside the stack (e.g. make wp ARGS=\"plugin list\")"
	@echo "  bootstrap       One-shot: install WP core + plugins + seed all content"
	@echo "  dump            Export current DB to db/dump.sql"
	@echo "  status          Show running services"
	@echo ""
	@echo "  hooks           Enable the repository's git hooks (run once per clone)"
	@echo "  test            Run every test suite"
	@echo "  verify-fast     Lint, format, types and unit tests (runs on every commit)"
	@echo "  verify          Full verification, including PostgreSQL tests and production build"
	@echo "  lib-release     Build the shared-auth wheel for its current version into wheels/"
	@echo "  lock            Re-resolve the services' uv.lock files (e.g. after a shared-auth pin change)"

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v
	@echo "Volumes wiped. Run 'make up' to start fresh from db/dump.sql"

logs:
	$(COMPOSE) logs -f wordpress db

wp:
	$(WPCLI) $(ARGS)

bootstrap:
	$(COMPOSE) run --rm --entrypoint bash wpcli /scripts/seed.sh

dump:
	@mkdir -p db
	$(COMPOSE) exec db sh -c 'mariadb-dump -u root -p"$$MYSQL_ROOT_PASSWORD" --default-character-set=utf8mb4 --add-drop-table --skip-extended-insert "$$MYSQL_DATABASE"' > db/dump.sql
	@echo "Wrote db/dump.sql ($$(wc -l < db/dump.sql) lines)"

status:
	$(COMPOSE) ps

hooks:
	git config core.hooksPath .githooks
	@echo "Git hooks enabled: every commit runs scripts/verify-fast.sh"

test:
	scripts/test.sh

verify-fast:
	scripts/verify-fast.sh

verify:
	scripts/verify.sh

lib-release:
	scripts/lib-release.sh

lock:
	scripts/lock.sh
