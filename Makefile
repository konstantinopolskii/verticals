# Verticals — command surface. docs/IMPLEMENTATION.md §6.5 names every target here; this file
# does not invent one it does not list. `make test` is the only command an agent needs, and
# the only one any work package's definition of done cites (§6.5, last line).
#
# Loads .env if present, so a developer who has copied .env.example -> .env and filled in the
# two required values gets a working `make migrate` / `make test` without exporting anything
# by hand. Nothing here invents a variable outside the frozen contract (§6.3).
ifneq (,$(wildcard .env))
include .env
export
endif

# Prefer the project's own venv when one exists (`python -m venv .venv && .venv/bin/pip install
# -e ".[dev]"` is the whole setup — nothing here creates or activates it). Falls back to
# `python3` for a container or CI image that installed straight into system Python. Override
# with `make migrate PYTHON=/some/other/python` if neither guess is right.
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

# ---------------------------------------------------------------------------------------------
# Test suites (E2E.md §1: core, http, mcp, ui, pipeline, perf, uidiff, static, harness).
#
# Every suite target below dispatches to `python -m tests.harness.runner` — the suite
# orchestrator, verdict block and artifacts/results.jsonl are docs/IMPLEMENTATION.md WP-06's
# deliverable (wave 1) and do not exist yet in wave 0. Until WP-06 lands, these targets fail
# with a clear "No module named tests.harness.runner" rather than a fabricated pass — per the
# WP-01 card: "No scenario can print a PASS line before WP-06 lands the runner. That is
# expected." `test-harness` is the one exception: E2E.md §12 says suite `harness` runs `make
# test` itself and judges the result, so routing it through the same dispatcher would recurse;
# it is plain pytest, always, and its own test drives `make test` as a subprocess.
#
# SCENARIO=/TIER=/MILESTONE= (E2E.md §12) pass straight through to whichever target is run.
RUNNER := $(PYTHON) -m tests.harness.runner
RUNNER_FLAGS :=
ifdef SCENARIO
RUNNER_FLAGS += --scenario $(SCENARIO)
endif
ifdef TIER
RUNNER_FLAGS += --tier $(TIER)
endif
ifdef MILESTONE
RUNNER_FLAGS += --milestone $(MILESTONE)
endif

.PHONY: test test-static test-core test-http test-mcp test-ui test-pipeline test-perf test-uidiff test-harness \
        db-up db-down migrate backup restore build-web lint

test:            ## everything runnable on this box (suite `harness` excluded — see test-harness)
	$(RUNNER) $(RUNNER_FLAGS)

test-static:     ## suite H — the source tree, read as files, no database
	$(RUNNER) --suite static $(RUNNER_FLAGS)

test-core:       ## suite A — real Postgres 16, no HTTP anywhere
	$(RUNNER) --suite core $(RUNNER_FLAGS)

test-http:       ## suite B — real uvicorn subprocess, real sockets
	$(RUNNER) --suite http $(RUNNER_FLAGS)

test-mcp:        ## suite C — real MCP client against the real server
	$(RUNNER) --suite mcp $(RUNNER_FLAGS)

test-ui:         ## suite D — Playwright against the real production build
	$(RUNNER) --suite ui $(RUNNER_FLAGS)

test-pipeline:   ## suite E — import, export, migrations, backup
	$(RUNNER) --suite pipeline $(RUNNER_FLAGS)

test-perf:       ## suite F — runs alone; no other suite holds workers while it does
	$(RUNNER) --suite perf $(RUNNER_FLAGS)

test-uidiff:     ## suite G — runs anywhere; reference fixtures are committed (S-101 gates: no mobile capture)
	$(RUNNER) --suite uidiff $(RUNNER_FLAGS)

test-harness:    ## suite I — runs `make test` itself and judges the artifacts (not part of `test`)
	$(PYTHON) -m pytest tests/harness -q

# ---------------------------------------------------------------------------------------------
# Database. docs/IMPLEMENTATION.md §6.2.

db-up:           ## start the test/CI Postgres (docker-compose.test.yml), wait for healthy
	docker compose -f docker-compose.test.yml up -d --wait

db-down:         ## stop it; tmpfs data dir means nothing survives this anyway
	docker compose -f docker-compose.test.yml down

migrate:         ## apply every outstanding migration against $VERTICALS_DATABASE_URL
	$(PYTHON) -m verticals.db.runner up

# Backup and restore. docs/ACCEPTANCE.md AC-166 and docs/E2E.md S-122 are what these two exist
# for: the criterion is not "a dump can be taken" (S-89 proved that months ago) but "the
# procedure a self-hoster reads in README.md actually restores". A documented procedure needs a
# command to document, so the two targets below are named by AC-166 rather than invented here,
# and docs/IMPLEMENTATION.md §6.5's list now carries them.
#
# `?=` and not `:=` on purpose: an operator who keeps backups on another volume sets BACKUP_FILE
# in the environment once and every `make backup` after that lands in the right place, with no
# edit to this file and no flag to remember. The default is deliberately a plain relative path in
# the working directory (gitignored) — a default under /var or ~ is a default that fails on a box
# where that path is not writable, at 03:00, in a cron job nobody is reading.

BACKUP_FILE ?= verticals-backup.dump

backup:          ## verified pg_dump -Fc of $VERTICALS_DATABASE_URL into $(BACKUP_FILE)
	$(PYTHON) -m verticals.db.backup dump --to $(BACKUP_FILE)

restore:         ## restore $(BACKUP_FILE) into $VERTICALS_DATABASE_URL (refuses a populated target)
	$(PYTHON) -m verticals.db.backup restore --from $(BACKUP_FILE)

# ---------------------------------------------------------------------------------------------
# Frontend. `web/` does not exist until docs/IMPLEMENTATION.md WP-12 (wave 2) — this target's
# job today is only to be the right shape when that lands (`R7` risk, IMPLEMENTATION.md §5:
# WP-01 owns "the first npm run build" as an early toolchain-drift signal; `.nvmrc` pins the
# version). Until then it fails with a plain "no such file" from npm, which is the honest
# wave-0 signal, not a fabricated pass.

build-web:       ## npm run build in web/
	npm --prefix web run build

# ---------------------------------------------------------------------------------------------
# Static checks. No new dependency: the 750-line rule is the literal command from
# ARCHITECTURE.md §2 ("Enforced in CI, because a rule nobody checks is a preference"); py_compile
# is stdlib. No style linter (ruff/flake8/black/...) is named anywhere in the frozen docs, so
# none is pinned here — adding one is a later, explicit decision, not a default.
#
# The line-count `find` covers `tests` as well as `verticals`, and that is a correction rather than
# an extension. It scoped to `verticals/` alone until `tests/http/test_security.py` was written at
# 777 lines and nothing objected — the author noticed and trimmed it by hand, which is precisely
# the situation the rule exists to make impossible. "Enforced in CI, because a rule nobody checks
# is a preference" applies to the checker's own blind spots too: a rule that cannot fire over half
# the tree is a preference over that half. The byte-compile pass deliberately stays on `verticals/`
# — it is an import-shape check on shipped code, and pytest already imports every test file.

lint:            ## the 750-line module rule + a byte-compile sanity pass over verticals/
	@echo "module line-count rule (ARCHITECTURE.md §2): no *.py over 750 lines"
	@find verticals tests -name '*.py' -exec awk 'FNR>750{print FILENAME": "FNR" lines"; nextfile}' {} + | { ! grep .; }
	@echo "byte-compiling verticals/ (cheap syntax/import-shape check)"
	@find verticals -name '*.py' -print0 | xargs -0 $(PYTHON) -m py_compile
	@echo "lint OK"
