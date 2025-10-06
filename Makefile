# =========================
# Configuración base
# =========================
SHELL := /bin/bash
.DEFAULT_GOAL := help

AWS_ENDPOINT ?= http://localhost:4566
REGION       ?= us-east-1

# Python / Pytest del venv
PY     := $(shell command -v python)
PYTEST := $(shell command -v pytest)

# Terraform local o en Docker (fallback automático)
TF_DOCKER = docker run --rm \
  -v "$(PWD)":/workspace -w /workspace \
  --network host \
  -u $$(id -u):$$(id -g) \
  -e AWS_ACCESS_KEY_ID=test -e AWS_SECRET_ACCESS_KEY=test -e AWS_DEFAULT_REGION=$(REGION) \
  hashicorp/terraform:1.9.5
TF := $(shell command -v terraform 2>/dev/null || echo $(TF_DOCKER))

# Descubrir lambdas por carpeta (un nivel)
LAMBDA_DIRS := $(shell find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | sort)
REQ_FILES   := $(shell find lambdas -mindepth 2 -maxdepth 2 -name requirements.txt | sort)

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
# Empaquetado (una o todas)
# =========================
.PHONY: package-% package-all
package-%: ## Empaqueta lambda %
	cd lambdas/$* && bash build.sh

package-all: $(addprefix package-,$(LAMBDA_DIRS)) ## Empaqueta todas las lambdas
	@echo "✅ Lambdas empaquetadas: $(LAMBDA_DIRS)"
# Tip: empaquetado en paralelo -> make -j $$(nproc) package-all

# =========================
# Terraform (plan/deploy/destroy)
# =========================
.PHONY: plan deploy nuke
plan: package-all ## Terraform plan contra LocalStack
	cd infra/terraform && $(TF) init && $(TF) plan

deploy: package-all ## Despliega recursos a LocalStack (autodescubre lambdas/*/dist.zip)
	cd infra/terraform && $(TF) init -upgrade && $(TF) apply -auto-approve

nuke: ## Elimina recursos de LocalStack (destroy con init previo)
	cd infra/terraform && $(TF) init -upgrade && $(TF) destroy -auto-approve

# =========================
# Dirs utilitarios
# =========================
.PHONY: ensure-dirs
ensure-dirs: ## Crea carpetas necesarias
	mkdir -p logs

# =========================
# Invocación y Logs (genéricos)
# =========================
.PHONY: invoke-% invoke logs-% logs-follow-% logs-quick-%
invoke-%: ## Invoca lambda % con payload de ejemplo
	$(PY) scripts/invoke.py --function $* --payload '{"name":"Camilo"}'

invoke: ## Invoca arbitraria: make invoke FN=<nombre> PAYLOAD='{"k":"v"}'
	$(PY) scripts/invoke.py --function "$(FN)" --payload '$(PAYLOAD)'

logs-%: ensure-dirs ## Muestra últimos logs (120s) de /aws/lambda/% y guarda en logs/%.log
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --since-seconds 120 \
		--output-file logs/$*.log --max-bytes 2000000 --backup-count 5 || true

logs-follow-%: ensure-dirs ## Sigue logs de /aws/lambda/% (idle=15s, máx 300s), guarda en logs/%.log
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --follow --idle-exit 15 --max-seconds 300 \
		--output-file logs/$*.log || true

logs-quick-%: ensure-dirs ## Tail rápido de /aws/lambda/% (idle=5s, máx 60s), guarda en logs/%.log
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --follow --since-seconds 30 --idle-exit 5 --max-seconds 60 \
		--output-file logs/$*.log || true

# =========================
# Listados / utilidades
# =========================
.PHONY: list-lambdas smoke
list-lambdas: ## Lista lambdas según Terraform output (requiere deploy previo)
	@cd infra/terraform && $(TF) output -json lambda_names | jq -r '.[]' || echo "Aún no hay output. Corre 'make deploy'."

smoke: ensure-dirs ## Invoca todas las Lambdas y muestra/guarda últimos logs
	@names=$$(cd infra/terraform && $(TF) output -json lambda_names 2>/dev/null | jq -r '.[]'); \
	if [ -z "$$names" ] || [ "$$names" = "null" ]; then \
	  echo "No hay output de Terraform; usando carpetas con dist.zip"; \
	  names=$$(find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n"); \
	fi; \
	for fn in $$names; do \
	  echo "==> Invoke $$fn"; \
	  $(PY) scripts/invoke.py --function $$fn --payload '{"name":"Smoke"}' || exit 1; \
	  echo "==> Logs $$fn (últimos 60s)"; \
	  $(PY) scripts/tail_logs.py --log-group /aws/lambda/$$fn --since-seconds 60 --output-file logs/$$fn.log || true; \
	  echo ""; \
	done

# =========================
# Tests
# =========================
.PHONY: test-unit test-integration test-integration-verbose
test-unit: ## Ejecuta tests unitarios (coverage)
	$(PYTEST) -q tests/unit

test-integration: ## Ejecuta tests de integración contra LocalStack (sin cobertura)
	$(PYTEST) -q --no-cov tests/integration

test-integration-verbose: ## Integración verbosa (muestra prints/tiempos)
	$(PYTEST) -vv -s --no-cov -rA --durations=5 tests/integration

# =========================
# Seguridad / calidad
# =========================
.PHONY: security-scan
security-scan: ## Bandit + pip-audit (por cada requirements.txt de lambdas)
	bandit -q -r lambdas -f txt || true
	@set -e; \
	for f in $(REQ_FILES); do \
	  echo "==> pip-audit $$f"; \
	  pip-audit -r "$$f" || true; \
	done

# =========================
# Alias de compatibilidad (legacy)
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
all: ## Pipeline completo: up -> package-all -> deploy -> list -> test -> smoke
	$(MAKE) up
	$(MAKE) package-all
	$(MAKE) deploy
	$(MAKE) list-lambdas
	$(MAKE) test-integration
	$(MAKE) smoke
	@echo "✅ ALL OK. Siguiente paso sugerido: 'make test-integration-verbose' o 'make logs-<fn>'"

all-verbose: ## Igual que 'all' pero incluye tests verbosos
	$(MAKE) all
	$(MAKE) test-integration-verbose

all-down: ## 'all' y luego apaga LocalStack
	$(MAKE) all
	$(MAKE) down

all-nuke: ## 'all', luego destroy de Terraform y apaga LocalStack
	$(MAKE) all
	$(MAKE) nuke
	$(MAKE) down
### END