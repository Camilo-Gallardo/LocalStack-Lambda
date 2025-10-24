# =========================
# Configuración base
# =========================
SHELL := /bin/bash
.DEFAULT_GOAL := help

AWS_ENDPOINT ?= http://localhost:4566
REGION       ?= us-east-1

PY     := $(shell command -v python3)
PYTEST := $(shell command -v pytest)

TF_DOCKER = docker run --rm \
  -v "$(PWD)":/workspace -w /workspace \
  --network host \
  -u $$(id -u):$$(id -g) \
  -e AWS_ACCESS_KEY_ID=test -e AWS_SECRET_ACCESS_KEY=test -e AWS_DEFAULT_REGION=$(REGION) \
  hashicorp/terraform:1.9.5
TF := $(shell command -v terraform 2>/dev/null || echo $(TF_DOCKER))

# Descubrir lambdas automáticamente
LAMBDA_DIRS := $(shell find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | sort)
REQ_FILES   := $(shell find lambdas -mindepth 2 -maxdepth 2 -name requirements.txt | sort)

# === Selector de suite ===
RUN ?= smoke
SMOKE_SINCE ?= 5
LOG_WINDOW ?= 60

# =========================
# Ayuda
# =========================
.PHONY: help
help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z0-9_.-]+:.*?##' $(lastword $(MAKEFILE_LIST)) | sort | \
		awk 'BEGIN {FS = ":.*?##"}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

# =========================
# Bootstrap
# =========================
.PHONY: bootstrap
bootstrap: ## Instala herramientas de desarrollo (incluyendo zip)
	@echo "🔧 Instalando dependencias..."
	@if ! command -v zip &> /dev/null; then \
		echo "⚠️  'zip' no encontrado, instalando..."; \
		sudo apt-get update && sudo apt-get install -y zip || \
		(echo "❌ No se pudo instalar 'zip'. Instálalo manualmente: sudo apt install zip" && exit 1); \
	fi
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r dev-requirements.txt
	@if command -v pre-commit &> /dev/null; then pre-commit install; fi
	@echo "✅ Bootstrap completo"

# =========================
# LocalStack
# =========================
.PHONY: up down clean
up: ## Levanta LocalStack
	docker compose up -d

down: ## Apaga LocalStack
	docker compose down -v

clean: ## Limpia archivos generados
	@echo "🧹 Limpiando..."
	@find lambdas -name "dist.zip" -delete 2>/dev/null || true
	@rm -f .lambdas_discovered.json .test_results.json
	@if [ -d .localstack ]; then \
		if [ -w .localstack ]; then \
			rm -rf .localstack; \
		else \
			sudo rm -rf .localstack; \
		fi \
	fi
	@echo "✅ Limpieza completa"

# =========================
# Auto-Discovery
# =========================
.PHONY: discover
discover: ## Auto-descubre lambdas
	@echo "🔍 Auto-descubriendo lambdas..."
	@$(PY) testing/auto_discovery.py

# =========================
# Empaquetado
# =========================
.PHONY: package-% package-all
SCRIPTS_DIR := scripts

package-%: ## Empaqueta lambda específica
	@echo "📦 Empaquetando lambda: $*"
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh $*

package-all: ## Empaqueta todas las lambdas
	@echo "📦 Empaquetando todas las lambdas..."
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh
	@echo "✅ Lambdas empaquetadas: $(LAMBDA_DIRS)"

# =========================
# Terraform
# =========================
.PHONY: plan deploy nuke
plan: ## Terraform plan
	cd infra/terraform && $(TF) init && $(TF) plan

deploy: ## Despliega a LocalStack
	@echo "🚀 Desplegando a LocalStack..."
	cd infra/terraform && $(TF) init -upgrade && $(TF) apply -auto-approve

nuke: ## Destruye infraestructura
	cd infra/terraform && $(TF) init -upgrade && $(TF) destroy -auto-approve || true

# =========================
# Dirs utilitarios
# =========================
.PHONY: ensure-dirs
ensure-dirs:
	@mkdir -p logs reports

# =========================
# Tests Automáticos
# =========================
.PHONY: test-auto
test-auto: ensure-dirs ## Tests automáticos para todas las lambdas
	@echo "🧪 Ejecutando tests automáticos..."
	@$(PY) testing/auto_test_runner.py || true
	@echo ""
	@echo "📋 Guardando logs de lambdas..."
	@names=$$(cat .lambdas_discovered.json | jq -r '.[].name'); \
	for fn in $$names; do \
	  echo "   📄 Guardando logs de $$fn..."; \
	  $(PY) scripts/tail_logs.py \
	    --log-group "/aws/lambda/$$fn" \
	    --since-seconds 300 \
	    --output-file "logs/$$fn.log" \
	    --max-bytes 2000000 \
	    --backup-count 5 2>/dev/null || echo "   ⚠️  No se pudieron obtener logs de $$fn"; \
	done
	@echo "✅ Logs guardados en logs/"
# =========================
# Invocación y Logs
# =========================
.PHONY: invoke-% invoke logs-% logs-follow-% logs-quick-%
invoke-%: ## Invoca lambda específica
	$(PY) scripts/invoke.py --function $* --payload '{"name":"Test"}'

invoke: ## FN=<nombre> PAYLOAD='{"k":"v"}'
	$(PY) scripts/invoke.py --function "$(FN)" --payload '$(PAYLOAD)'

logs-%: ensure-dirs
	@rm -f logs/$*.log
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --since-seconds $(SMOKE_SINCE) \
	  --output-file logs/$*.log --max-bytes 2000000 --backup-count 5 || true

logs-follow-%: ensure-dirs
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --follow --idle-exit 15 --max-seconds 300 \
	  --output-file logs/$*.log || true

logs-quick-%: ensure-dirs
	$(PY) scripts/tail_logs.py --log-group /aws/lambda/$* --follow --since-seconds 30 --idle-exit 5 --max-seconds 60 \
	  --output-file logs/$*.log || true

# =========================
# Smoke Tests
# =========================
.PHONY: smoke list-lambdas
list-lambdas:
	@cd infra/terraform && $(TF) output -json lambda_names | jq -r '.[]' || echo "Run 'make deploy' first"

smoke: ensure-dirs
	@names=$$(cd infra/terraform && $(TF) output -json lambda_names 2>/dev/null | jq -r '.[]'); \
	if [ -z "$$names" ] || [ "$$names" = "null" ]; then \
	  echo "No output from Terraform, using discovered lambdas"; \
	  names=$$(cat .lambdas_discovered.json | jq -r '.[].name'); \
	fi; \
	for fn in $$names; do \
	  echo "==> Invoke $$fn"; \
	  "$(PY)" "scripts/invoke.py" --function "$$fn" --payload '{"name":"Smoke"}' || exit 1; \
	  echo "==> Logs $$fn (last $(LOG_WINDOW)s)"; \
	  "$(PY)" "scripts/tail_logs.py" \
	    --log-group "/aws/lambda/$$fn" \
	    --since-seconds "$(LOG_WINDOW)" \
	    --output-file "logs/$$fn.log" \
	    --max-bytes "2000000" \
	    --backup-count "5" || true; \
	  echo ""; \
	done

# =========================
# Tests tradicionales
# =========================
.PHONY: test-unit test-integration test-integration-verbose
test-unit: ## Unit tests
	$(PYTEST) -q tests/unit

test-integration: ## Tests de integración
	$(PYTEST) -q --no-cov tests/integration

test-integration-verbose: ## Tests de integración (verbose)
	$(PYTEST) -vv -s --no-cov -rA --durations=5 tests/integration

# =========================
# Suite selector
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
# Seguridad
# =========================
.PHONY: security-scan
security-scan: ensure-dirs ## Análisis de seguridad (Bandit + pip-audit)
	@echo "🔒 Ejecutando análisis de seguridad..."
	@bandit -r lambdas -f json -o reports/bandit_report.json --quiet || true
	@echo "" > reports/pip_audit_report.txt
	@set -e; \
	for f in $(REQ_FILES); do \
	  echo "==> pip-audit $$f"; \
	  echo "=== Auditing $$f ===" >> reports/pip_audit_report.txt; \
	  pip-audit -r "$$f" >> reports/pip_audit_report.txt 2>&1 || true; \
	  echo "" >> reports/pip_audit_report.txt; \
	done
	@$(PY) scripts/security_console_report.py || true
	@echo "✅ Reportes guardados:"
	@echo "   - Bandit: reports/bandit_report.json"
	@echo "   - pip-audit: reports/pip_audit_report.txt"
	@echo "   - Consolidado: reports/security_console_report.json"
# =========================
# Pipeline Completo
# =========================
.PHONY: all
all: ensure-dirs ## Pipeline completo (automático)
	@echo "🚀 Iniciando pipeline completo..."
	$(MAKE) up
	$(MAKE) discover
	$(MAKE) package-all
	$(MAKE) deploy
	$(MAKE) list-lambdas
	$(MAKE) test-auto
	$(MAKE) run-suite
	$(MAKE) security-scan
	@echo ""
	@echo "✅ Pipeline completado"
	@echo "📊 Para ver reportes:"
	@echo "   - Security: reports/security_console_report.json"
	@echo "   - Bandit: reports/bandit_report.json"
	@echo "   - pip-audit: reports/pip_audit_report.txt"
	@echo "   - Tests: .test_results.json"
	@echo "   - Logs: logs/*.log"

all-verbose: ## Pipeline con tests verbose
	$(MAKE) RUN=both up discover package-all deploy list-lambdas test-auto run-suite
	$(MAKE) test-integration-verbose
	$(MAKE) security-scan

all-down: ## Pipeline + apagar LocalStack
	$(MAKE) all
	$(MAKE) down

all-nuke: ## Destruir todo
	$(MAKE) nuke
	$(MAKE) down
	$(MAKE) clean

# =========================
# Reporte final
# =========================
.PHONY: report
report: ## Genera reporte consolidado
	@echo "📊 Generando reporte final..."
	@$(PY) testing/report_generator.py