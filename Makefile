INFRA_APP := infra/app
INFRA_BOOTSTRAP := infra/bootstrap

.PHONY: setup check lint typecheck test test-db db-up db-down run migrate build-index export-schema \
        evals evals-retrieval compare smoke voice-listen voice-smoke infra-check infra-init infra-plan infra-apply

# Locked install with every extra; CI and local use the same command.
setup:
	uv sync --locked --all-extras

check: lint typecheck test

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy

# Offline suite: no network, no Postgres, no credentials. Postgres-marked tests are skipped.
test:
	uv run pytest --cov

# Postgres-backed tests against the compose database (or CAFE_NORTE_TEST_DATABASE_URL if set).
test-db: db-up
	CAFE_NORTE_TEST_DATABASE_URL=$${CAFE_NORTE_TEST_DATABASE_URL:-postgresql://cafe:cafe@localhost:5432/cafe_norte_test} \
		uv run pytest -m postgres

db-up:
	docker compose up -d --wait postgres

db-down:
	docker compose down

run:
	uv run uvicorn cafe_norte.main:create_default_app --factory --port 8000 $(if $(wildcard .env),--env-file .env)

migrate:
	uv run python -m cafe_norte.persistence.migrate

build-index:
	uv run python scripts/build_index.py

# Regenerates examples/session_export.schema.json from the Pydantic export model.
export-schema:
	uv run python scripts/export_schema.py

# Paid, manual, local. Needs a running server with a real model (evals/README.md).
evals:
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run $(ARGS)

evals-retrieval:
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run --suite retrieval $(ARGS)

compare:
	set -a; [ -f .env ] && . ./.env; set +a; uv run python -m evals.run --suite comparison $(ARGS)

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
