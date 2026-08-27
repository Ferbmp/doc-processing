DC ?= docker compose

.PHONY: help up down logs migrate migrations test lint typecheck seed psql worker reap scale-workers

help:
	@echo "up              start db, api, worker and web"
	@echo "down            stop everything (add ARGS=-v to drop the database)"
	@echo "logs            tail all service logs"
	@echo "migrations      generate migrations for the documents app"
	@echo "migrate         apply migrations"
	@echo "seed            submit one demo document per processing outcome"
	@echo "test            run the pytest suite inside the api container"
	@echo "lint            ruff over the backend"
	@echo "typecheck       tsc over the frontend"
	@echo "worker          run a single worker pass in the foreground"
	@echo "reap            recover jobs abandoned by dead workers"
	@echo "scale-workers   run three concurrent workers"
	@echo "psql            open a psql shell"

up:
	$(DC) up -d --build
	@echo "\nUI:  http://localhost:5173\nAPI: http://localhost:8000/api/documents/"

down:
	$(DC) down $(ARGS)

logs:
	$(DC) logs -f

migrations:
	$(DC) run --rm api python manage.py makemigrations documents

migrate:
	$(DC) run --rm api python manage.py migrate

seed:
	$(DC) exec api python manage.py seed_demo

test:
	$(DC) run --rm api pytest

lint:
	$(DC) run --rm --no-deps --entrypoint ruff api check .

typecheck:
	$(DC) exec web npm run typecheck

worker:
	$(DC) run --rm worker python manage.py process_documents --once

reap:
	$(DC) exec api python manage.py reap_stale_jobs

scale-workers:
	$(DC) up -d --scale worker=3

psql:
	$(DC) exec db psql -U tally -d tally
