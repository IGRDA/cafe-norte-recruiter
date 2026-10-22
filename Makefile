INFRA_APP := infra/app
INFRA_BOOTSTRAP := infra/bootstrap

.PHONY: setup check preview preflight web-check web-build web-dev lint typecheck test test-unit test-component test-http test-e2e quality test-db db-up db-down run migrate build-index export-schema export-example \
        evals evals-retrieval compare evals-signals smoke voice-listen voice-smoke infra-check infra-init infra-plan infra-apply

# Locked install with every extra; CI and local use the same command.
setup:
	uv sync --locked --all-extras
	npm --prefix web ci --no-audit --no-fund

check: lint typecheck test web-check

# The branch as production runs it, on this laptop: Postgres, real model, Jev, voice (D64).
# Prints the link to call before merging.
preview:
	./scripts/preview.sh

# The gate before a merge (D64): the offline checks, the Postgres suite, then live on the
# configured model with the behavioural invariants: Spanish and English to the end, a goodbye
# with the summary pending, a switch to German (about €0.4; the estimate is printed first).
PREFLIGHT_LIVE := S01 S02 S33 S34
preflight: check test-db
	$(MAKE) evals ARGS="--suite scenarios --mode live --only $(PREFLIGHT_LIVE) --yes"

# The page (D61): types, lint and Vitest; offline once `make setup` has installed web/node_modules.
web-check:
	npm --prefix web run check

web-build:
	npm --prefix web run build

# The page on :5173 with hot reload, proxying /api to `make run` on :8000.
web-dev:
	npm --prefix web run dev

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy

# Offline suite: no network, no Postgres, no credentials. Postgres-marked tests are skipped.
test:
	uv run pytest --cov

# One layer of the pyramid (tests/README.md); no coverage floor, for a fast loop.
test-unit test-component test-http test-e2e:
	uv run pytest tests/$(@:test-%=%)

# Manual (D50): the suite's shape and strength in .quality/report.md: tests per layer,
# properties, coverage, the slowest tests and the mutation score of the pure modules.
# PROFILE=deep runs 2000 examples per property (about four minutes) instead of CI's 300.
quality:
	mkdir -p .quality
	HYPOTHESIS_PROFILE=$(or $(PROFILE),ci) uv run pytest -q --cov --cov-report=json:.quality/coverage.json --junitxml=.quality/junit.xml
	rm -rf mutants  # mutmut keeps old verdicts when only the tests change
	HYPOTHESIS_PROFILE=ci uv run mutmut run --max-children 8 > .quality/mutmut.log 2>&1
	uv run python scripts/quality_report.py

# Postgres-backed tests against the compose database (or CAFE_NORTE_TEST_DATABASE_URL if set).
test-db: db-up
	CAFE_NORTE_TEST_DATABASE_URL=$${CAFE_NORTE_TEST_DATABASE_URL:-postgresql://cafe:cafe@localhost:5432/cafe_norte_test} \
		uv run pytest -m postgres

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

run: web-build
	uv run uvicorn cafe_norte.main:create_default_app --factory --port 8000 $(if $(wildcard .env),--env-file .env)

migrate:
	uv run python -m cafe_norte.persistence.migrate

build-index:
	uv run python scripts/build_index.py

# Regenerates examples/session_export.schema.json from the Pydantic export model, and the page's
# contract schema and its TypeScript types (web/src/api/contracts.*).
export-schema:
	uv run python scripts/export_schema.py
	npm --prefix web run types

# Regenerates examples/session_export.example.json by replaying scenario S01 offline.
export-example:
	uv run python -m evals.export_example

# Paid, manual, local. Needs a running server with a real model (evals/README.md).
evals:
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run $(ARGS)

evals-retrieval:
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run --suite retrieval $(ARGS)

compare:
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run --suite comparison $(ARGS)

# Offline experiment: sentiment and reply language, regex vs classifier vs LLM vs Jev.
evals-signals:
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run --suite signals $(ARGS)

smoke:
	uv run python scripts/smoke.py $${SMOKE_URL:-http://localhost:8000}

# Manual, paid: the ElevenLabs listening check (writes /tmp/voices/*.mp3).
voice-listen:
	uv run python scripts/voice_listen.py $(ARGS)

# Manual, paid: hosted voice from the laptop. Needs the Daily, Deepgram and ElevenLabs keys in .env.
voice-smoke:
	CAFE_NORTE_VOICE=pipecat uv run uvicorn cafe_norte.main:create_default_app --factory --port 8000 --env-file .env

infra-check:
	terraform -chdir=$(INFRA_BOOTSTRAP) fmt -check -recursive
	terraform -chdir=$(INFRA_APP) fmt -check -recursive
	terraform -chdir=$(INFRA_BOOTSTRAP) init -backend=false -input=false >/dev/null
	terraform -chdir=$(INFRA_BOOTSTRAP) validate
	terraform -chdir=$(INFRA_APP) init -backend=false -input=false >/dev/null
	terraform -chdir=$(INFRA_APP) validate

infra-init:
	terraform -chdir=$(INFRA_APP) init -input=false -backend-config=../environments/demo.backend.hcl

infra-plan:
	terraform -chdir=$(INFRA_APP) plan -input=false -var-file=../environments/demo.tfvars

infra-apply:
	terraform -chdir=$(INFRA_APP) apply -input=false -var-file=../environments/demo.tfvars
