# HazeReady. Run `make help` for the list.
.DEFAULT_GOAL := help
PY := .venv/bin/python
PIP := .venv/bin/pip
PYTHON311 ?= python3.11

.PHONY: help setup validate index web run eval report test lint clean demo

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv, install Python deps, build the frontend and the index
	$(PYTHON311) -m venv .venv
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements.txt
	cd web && npm install && npm run build
	$(MAKE) validate
	$(MAKE) index

validate: ## Validate the corpus and policy matrix; writes data/manifest.yaml
	$(PY) scripts/validate_corpus.py

index: ## Build the FAISS + BM25 index from data/corpus/
	$(PY) scripts/build_index.py

web: ## Build the frontend bundle into web/dist
	cd web && npm install && npm run build

run: ## Serve the app on http://localhost:8000
	.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

demo: ## Serve the app fully offline, from committed fixtures, with no API key
	OFFLINE_MODE=true LLM_PROVIDER=stub .venv/bin/uvicorn app.main:app --port 8000

eval: ## Run the full ablation grid, rebuild the report, refresh the README table
	$(PY) eval/runner.py --runs 3
	$(PY) eval/report_builder.py
	$(PY) scripts/inject_results.py

report: ## Rebuild the report and README table from existing reports/raw/
	$(PY) eval/report_builder.py
	$(PY) scripts/inject_results.py

benchmark: ## Regenerate and re-freeze the HazeQA benchmark
	$(PY) eval/hazeqa/author_items.py
	$(PY) eval/hazeqa/check_agreement.py

test: ## Run the test suite, corpus validation and the README claim audit
	$(PY) -m pytest -q
	$(PY) scripts/validate_corpus.py
	-$(PY) scripts/audit_readme.py

audit: ## Check every quantitative README claim against the repo
	$(PY) scripts/audit_readme.py

lint: ## Lint and format-check
	.venv/bin/ruff check app eval scripts tests
	.venv/bin/ruff format --check app eval scripts tests

clean: ## Remove build artefacts and caches (keeps the corpus and benchmark)
	rm -rf data/index data/telemetry.db data/telemetry.db-wal data/telemetry.db-shm
	rm -rf .pytest_cache **/__pycache__ web/dist
