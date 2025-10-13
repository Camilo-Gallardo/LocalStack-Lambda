# =========================
# Configuración base
# =========================
SHELL := /bin/bash
.DEFAULT_GOAL := help

AWS_ENDPOINT ?= http://localhost:4566
REGION       ?= us-east-1

PY     := $(shell command -v python)
PYTEST := $(shell command -v pytest)

TF_DOCKER = docker run --rm \
  -v "$(PWD)":/workspace -w /workspace \
  --network host \
  -u $$(id -u):$$(id -g) \
  -e AWS_ACCESS_KEY_ID=test -e AWS_SECRET_ACCESS_KEY=test -e AWS_DEFAULT_REGION=$(REGION) \
  hashicorp/terraform:1.9.5
TF := $(shell command -v terraform 2>/dev/null || echo $(TF_DOCKER))

# Descubrir lambdas por carpeta
LAMBDA_DIRS := $(shell find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | sort)
REQ_FILES   := $(shell find lambdas -mindepth 2 -maxdepth 2 -name requirements.txt | sort)

# === Selector de suite ===
# RUN = smoke | tests | both
RUN ?= smoke

# Ventana de logs para SMOKE (segundos, pequeña para no traer invocaciones viejas)
SMOKE_SINCE ?= 5

# =========================
# Ayuda
# =========================
.PHONY: help
help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z0-9_.-]+:.*?##' $(lastword $(MAKEFILE_LIST)) | sort | \
		awk 'BEGIN {FS = ":.*?##"}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# =========================
# Bootstrap / LocalStack
# =========================
.PHONY: bootstrap up down
bootstrap: ## Instala herramientas de desarrollo
	$(PY) -m pip install -r dev-requirements.txt
	pre-commit install

up: ## Levanta LocalStack
	docker compose up -d

down: ## Apaga LocalStack y limpia volúmenes
	docker compose down -v

# =========================
# Empaquetado
# =========================
.PHONY: package-% package-all
SCRIPTS_DIR := scripts

package-%: ## Empaqueta lambda %
	@echo "==> Packaging lambda: $*"
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh $*

package-all: ## Empaqueta todas las lambdas
	@echo "==> Packaging all lambdas"
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh
	@echo "✅ Lambdas empaquetadas: $(LAMBDA_DIRS)"

# =========================
# Terraform
# =========================
.PHONY: plan deploy nuke
plan: ## Terraform plan contra LocalStack (requiere dist.zip listo)
	cd infra/terraform && $(TF) init && $(TF) plan

deploy: ## Despliega recursos a LocalStack (no re-empaqueta)
	cd infra/terraform && $(TF) init -upgrade && $(TF) apply -auto-approve

nuke: ## Destroy + init (para asegurar proveedor)
	cd infra/terraform && $(TF) init -upgrade && $(TF) destroy -auto-approve || true

# =========================
# Dirs utilitarios
# =========================
.PHONY: ensure-dirs
ensure-dirs:
	mkdir -p logs

# =========================
# Invocación y Logs
# =========================
.PHONY: invoke-% invoke logs-% logs-follow-% logs-quick-%
invoke-%: ## Invoca lambda % con payload de ejemplo
	$(PY) scripts/invoke.py --function $* --payload '{"name":"Camilo"}'

invoke: ## FN=<nombre> PAYLOAD='{"k":"v"}'
	$(PY) scripts/invoke.py --function "$(FN)" --payload '$(PAYLOAD)'

logs-%: ensure-dirs ## Últimos logs (ventana corta) y guarda en logs/%.log
	@rm -f logs/$*.log
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --since-seconds $(SMOKE_SINCE) \
	  --output-file logs/$*.log --max-bytes 2000000 --backup-count 5 || true

logs-follow-%: ensure-dirs
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --follow --idle-exit 15 --max-seconds 300 \
	  --output-file logs/$*.log || true

logs-quick-%: ensure-dirs
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --follow --since-seconds 30 --idle-exit 5 --max-seconds 60 \
	  --output-file logs/$*.log || true

# Ventana configurable para smoke (en segundos)
LOG_WINDOW ?= 60

# =========================
# Listados / utilidades
# =========================
.PHONY: smoke
list-lambdas:
	@cd infra/terraform && $(TF) output -json lambda_names | jq -r '.[]' || echo "Aún no hay output. Corre 'make deploy'."

smoke: ensure-dirs
	@names=$$(cd infra/terraform && $(TF) output -json lambda_names 2>/dev/null | jq -r '.[]'); \
	if [ -z "$$names" ] || [ "$$names" = "null" ]; then \
	  echo "No hay output de Terraform; usando carpetas con dist.zip"; \
	  names=$$(find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n"); \
	fi; \
	for fn in $$names; do \
	  echo "==> Invoke $$fn"; \
	  "$(PY)" "scripts/invoke.py" --function "$$fn" --payload '{"name":"Smoke"}' || exit 1; \
	  echo "==> Logs $$fn (últimos $(LOG_WINDOW)s)"; \
	  "$(PY)" "scripts/tail_logs.py" \
	    --log-group "/aws/lambda/$$fn" \
	    --since-seconds "$(LOG_WINDOW)" \
	    --output-file "logs/$$fn.log" \
	    --max-bytes "2000000" \
	    --backup-count "5" || true; \
	  echo ""; \
	done



# =========================
# Tests
# =========================
.PHONY: test-unit test-integration test-integration-verbose
test-unit: ## Unit tests
	$(PYTEST) -q tests/unit

test-integration: ## Integración contra LocalStack
	$(PYTEST) -q --no-cov tests/integration

test-integration-verbose: ## Integración verbosa
	$(PYTEST) -vv -s --no-cov -rA --durations=5 tests/integration

# =========================
# Suite selector (RUN = smoke|tests|both)
# =========================
.PHONY: run-suite
run-suite:
	@if [ "$(RUN)" = "tests" ]; then \
	  $(MAKE) test-integration; \
	elif [ "$(RUN)" = "smoke" ]; then \
	  $(MAKE) smoke; \
	else \
	  $(MAKE) test-integration && $(MAKE) smoke; \
	fi

# =========================
# Seguridad / calidad
# =========================
.PHONY: security-scan
security-scan: ## Bandit + pip-audit
	bandit -q -r lambdas -f txt || true
	@set -e; \
	for f in $(REQ_FILES); do \
	  echo "==> pip-audit $$f"; \
	  pip-audit -r "$$f" || true; \
	done

# =========================
# Alias (legacy)
# =========================
.PHONY: package-hello invoke-hello logs-hello logs-hello-follow logs-hello-quick
package-hello: package-hello_world
invoke-hello:  invoke-hello_world
logs-hello:    logs-hello_world
logs-hello-follow: logs-follow-hello_world
logs-hello-quick:  logs-quick-hello_world

# =========================
# Pipelines "one-shot"
# =========================
.PHONY: all all-verbose all-down all-nuke
all: ## up -> package-all -> deploy -> list -> (smoke/tests/both)
	$(MAKE) up
	$(MAKE) package-all
	$(MAKE) deploy
	$(MAKE) list-lambdas
	$(MAKE) run-suite
	@echo "✅ ALL OK. RUN=$(RUN). Sugerencia: 'make test-integration-verbose' o 'make logs-<fn>'"

all-verbose: ## all (both) + integración verbosa
	$(MAKE) RUN=both up package-all deploy list-lambdas run-suite
	$(MAKE) test-integration-verbose

all-down: ## all y luego apaga LocalStack
	$(MAKE) all
	$(MAKE) down

all-nuke: ## destroy + down
	$(MAKE) nuke
	$(MAKE) down
# =========================
# Fin del Makefile
# =========================
