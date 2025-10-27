# =============================================================================
# LocalStack Lambda CI/CD Pipeline (Legacy Version)
# =============================================================================
# Makefile para desarrollo, testing y deployment de AWS Lambdas en LocalStack
# Versión anterior sin auto-discovery ni mock injection
# =============================================================================

# =========================
# Configuración Base
# =========================
SHELL := /bin/bash
.DEFAULT_GOAL := help

# AWS Configuration
AWS_ENDPOINT ?= http://localhost:4566
REGION       ?= us-east-1

# Python & Tools
PY     := $(shell command -v python)
PYTEST := $(shell command -v pytest)

# Terraform (local o Docker fallback)
TF_DOCKER = docker run --rm \
  -v "$(PWD)":/workspace -w /workspace \
  --network host \
  -u $$(id -u):$$(id -g) \
  -e AWS_ACCESS_KEY_ID=test \
  -e AWS_SECRET_ACCESS_KEY=test \
  -e AWS_DEFAULT_REGION=$(REGION) \
  hashicorp/terraform:1.9.5
TF := $(shell command -v terraform 2>/dev/null || echo $(TF_DOCKER))

# Discovery de lambdas por carpeta
LAMBDA_DIRS := $(shell find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n" 2>/dev/null | sort)
REQ_FILES   := $(shell find lambdas -mindepth 2 -maxdepth 2 -name requirements.txt 2>/dev/null | sort)

# Test suite selector
RUN ?= smoke

# Ventana de logs para smoke (segundos)
SMOKE_SINCE ?= 5
LOG_WINDOW ?= 60

# Directories
SCRIPTS_DIR := scripts

# =========================
# Ayuda
# =========================
.PHONY: help
help: ## Muestra esta ayuda
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  LocalStack Lambda CI/CD Pipeline (v1.0)                    ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "📋 Comandos disponibles:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_.-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "💡 Ejemplos:"
	@echo "  make all                  # Pipeline completo"
	@echo "  make up deploy            # Solo deploy"
	@echo "  make invoke-hello_world   # Invocar lambda"
	@echo ""

# =========================
# Bootstrap & Setup
# =========================
.PHONY: bootstrap
bootstrap: ## Instala herramientas de desarrollo
	@echo "Instalando dependencias..."
	@$(PY) -m pip install -r dev-requirements.txt --quiet
	@if command -v pre-commit &> /dev/null; then pre-commit install; fi
	@echo "✅ Bootstrap completo"

# =========================
# LocalStack Management
# =========================
.PHONY: up down
up: ## Levanta LocalStack
	@echo "Iniciando LocalStack..."
	@docker compose up -d
	@echo "✅ LocalStack corriendo en $(AWS_ENDPOINT)"

down: ## Apaga LocalStack y limpia volúmenes
	@echo "Deteniendo LocalStack..."
	@docker compose down -v
	@echo "✅ LocalStack detenido"

# =========================
# Directorios
# =========================
.PHONY: ensure-dirs
ensure-dirs:
	@mkdir -p logs reports

# =========================
# Empaquetado
# =========================
.PHONY: package-% package-all
package-%: ## Empaqueta lambda específica (ej: package-hello_world)
	@echo "📦 Empaquetando lambda: $*"
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh $* 2>&1 | \
		grep -E '(^Packaging|^OK:|ERROR|WARNING)' || true
	@echo ""

package-all: ## Empaqueta todas las lambdas
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  📦 Empaquetando todas las lambdas...                        ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh 2>&1 | \
		grep -E '(^Packaging|^OK:|ERROR|WARNING)' || true
	@echo ""
	@echo "✅ Lambdas empaquetadas:"
	@for dir in $(LAMBDA_DIRS); do echo "   ✓ $$dir"; done
	@echo ""

# =========================
# Terraform / Infrastructure
# =========================
.PHONY: plan deploy nuke
plan: ## Terraform plan (preview de cambios)
	@echo "🔍 Ejecutando terraform plan..."
	@cd infra/terraform && \
		$(TF) init -input=false > /dev/null 2>&1 && \
		$(TF) plan -input=false

deploy: ## Despliega infraestructura a LocalStack
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🚀 Desplegando a LocalStack...                              ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@cd infra/terraform && \
		$(TF) init -upgrade -input=false > /dev/null 2>&1 && \
		$(TF) apply -auto-approve -input=false 2>&1 | \
		grep -E '(Apply complete|Error|module\.|aws_lambda_function\.)' || true
	@echo ""
	@echo "✅ Deployment completado"
	@echo ""

nuke: ## Destruye infraestructura
	@echo "💣 Destruyendo infraestructura..."
	@cd infra/terraform && \
		$(TF) init -upgrade -input=false > /dev/null 2>&1 && \
		$(TF) destroy -auto-approve -input=false 2>&1 | \
		grep -E '(Destroy complete|Error)' || true
	@echo "✅ Infraestructura destruida"

# =========================
# Invocación Manual
# =========================
.PHONY: invoke-% invoke
invoke-%: ## Invoca lambda específica (ej: invoke-hello_world)
	@echo "📞 Invocando lambda: $*"
	@$(PY) $(SCRIPTS_DIR)/invoke.py --function $* --payload '{"name":"Camilo"}'

invoke: ## Invoca lambda custom: FN=nombre PAYLOAD='{"k":"v"}'
	@if [ -z "$(FN)" ]; then \
		echo "❌ Error: Especifica FN=nombre_lambda"; \
		echo "   Ejemplo: make invoke FN=hello_world PAYLOAD='{\"test\":true}'"; \
		exit 1; \
	fi
	@echo "📞 Invocando $(FN)..."
	@$(PY) $(SCRIPTS_DIR)/invoke.py --function "$(FN)" --payload '$(PAYLOAD)'

# =========================
# Logs
# =========================
.PHONY: logs-% logs-follow-% logs-quick-%
logs-%: ensure-dirs ## Ver logs de lambda (ej: logs-hello_world)
	@echo "📜 Obteniendo logs de $*..."
	@rm -f logs/$*.log
	@$(PY) $(SCRIPTS_DIR)/tail_logs.py \
		--log-group /aws/lambda/$* \
		--since-seconds $(SMOKE_SINCE) \
		--output-file logs/$*.log \
		--max-bytes 2000000 \
		--backup-count 5 || true
	@echo "✅ Logs guardados en logs/$*.log"

logs-follow-%: ensure-dirs ## Sigue logs en tiempo real (ej: logs-follow-hello_world)
	@echo "📜 Siguiendo logs de $* en tiempo real..."
	@$(PY) $(SCRIPTS_DIR)/tail_logs.py \
		--log-group /aws/lambda/$* \
		--follow \
		--idle-exit 15 \
		--max-seconds 300 \
		--output-file logs/$*.log || true

logs-quick-%: ensure-dirs ## Ver últimos logs rápidos (30s)
	@echo "📜 Logs rápidos de $*..."
	@$(PY) $(SCRIPTS_DIR)/tail_logs.py \
		--log-group /aws/lambda/$* \
		--follow \
		--since-seconds 30 \
		--idle-exit 5 \
		--max-seconds 60 \
		--output-file logs/$*.log || true

# =========================
# Listados y Smoke Tests
# =========================
.PHONY: list-lambdas smoke
list-lambdas: ## Lista lambdas desplegadas
	@echo "📋 Lambdas desplegadas:"
	@cd infra/terraform && $(TF) output -json lambda_names 2>/dev/null | jq -r '.[]' | \
		awk '{print "   ✓ " $$0}' || echo "   ⚠️  Ejecuta 'make deploy' primero"

smoke: ensure-dirs ## Smoke tests (invoca todas las lambdas)
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🔥 Ejecutando smoke tests...                                ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@names=$$(cd infra/terraform && $(TF) output -json lambda_names 2>/dev/null | jq -r '.[]'); \
	if [ -z "$$names" ] || [ "$$names" = "null" ]; then \
	  echo "⚠️  No hay output de Terraform, usando carpetas con dist.zip..."; \
	  names=$$(find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n"); \
	fi; \
	for fn in $$names; do \
	  echo ""; \
	  echo "==> Invoke $$fn"; \
	  "$(PY)" "$(SCRIPTS_DIR)/invoke.py" --function "$$fn" --payload '{"name":"Smoke"}' || exit 1; \
	  echo "==> Logs $$fn (últimos $(LOG_WINDOW)s)"; \
	  "$(PY)" "$(SCRIPTS_DIR)/tail_logs.py" \
	    --log-group "/aws/lambda/$$fn" \
	    --since-seconds "$(LOG_WINDOW)" \
	    --output-file "logs/$$fn.log" \
	    --max-bytes "2000000" \
	    --backup-count "5" || true; \
	done
	@echo ""
	@echo "✅ Smoke tests completados"

# =========================
# Tests Tradicionales
# =========================
.PHONY: test-unit test-integration test-integration-verbose
test-unit: ## Unit tests
	@echo "🧪 Ejecutando unit tests..."
	@$(PYTEST) -q tests/unit

test-integration: ## Tests de integración
	@echo "🧪 Ejecutando tests de integración..."
	@$(PYTEST) -q --no-cov tests/integration

test-integration-verbose: ## Tests de integración (verbose)
	@echo "🧪 Ejecutando tests de integración (verbose)..."
	@$(PYTEST) -vv -s --no-cov -rA --durations=5 tests/integration

# =========================
# Suite Selector
# =========================
.PHONY: run-suite
run-suite: ## Ejecuta suite de tests (RUN=smoke|tests|both)
	@echo "🎯 Ejecutando suite: $(RUN)"
	@if [ "$(RUN)" = "tests" ]; then \
	  $(MAKE) --no-print-directory test-integration; \
	elif [ "$(RUN)" = "smoke" ]; then \
	  $(MAKE) --no-print-directory smoke; \
	else \
	  $(MAKE) --no-print-directory test-integration && $(MAKE) --no-print-directory smoke; \
	fi

# =========================
# Security Scanning
# =========================
.PHONY: security-scan
security-scan: ensure-dirs ## Análisis de seguridad (Bandit + pip-audit)
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🔒 Ejecutando análisis de seguridad...                      ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@bandit -r lambdas -f json -o reports/bandit_report.json --quiet 2>/dev/null || true
	@echo "" > reports/pip_audit_report.txt
	@for f in $(REQ_FILES); do \
	  echo "==> pip-audit $$f"; \
	  pip-audit -r "$$f" >> reports/pip_audit_report.txt 2>&1 || true; \
	done
	@python3 $(SCRIPTS_DIR)/security_console_report.py 2>/dev/null || true
	@echo ""
	@echo "✅ Reportes de seguridad guardados:"
	@echo "   📄 Bandit:  reports/bandit_report.json"
	@echo "   📄 Audit:   reports/pip_audit_report.txt"
	@echo ""

# =========================
# Alias Legacy
# =========================
.PHONY: package-hello invoke-hello logs-hello logs-hello-follow logs-hello-quick
package-hello: package-hello_world
invoke-hello:  invoke-hello_world
logs-hello:    logs-hello_world
logs-hello-follow: logs-follow-hello_world
logs-hello-quick:  logs-quick-hello_world

# =========================
# Pipelines Completos
# =========================
.PHONY: all all-verbose all-down all-nuke
all: ## Pipeline completo (up → package → deploy → tests → security)
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🚀 PIPELINE                                                 ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@$(MAKE) --no-print-directory up
	@$(MAKE) --no-print-directory package-all
	@$(MAKE) --no-print-directory deploy
	@$(MAKE) --no-print-directory list-lambdas
	@$(MAKE) --no-print-directory run-suite
	@$(MAKE) --no-print-directory security-scan
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  ✅ PIPELINE COMPLETADO                                      ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "📊 Suite ejecutada: RUN=$(RUN)"
	@echo "📜 Logs guardados en: logs/"
	@echo "🔒 Reportes en: reports/"
	@echo ""
	@echo "💡 Comandos útiles:"
	@echo "   make test-integration-verbose    # Tests verbosos"
	@echo "   make logs-hello_world            # Ver logs"
	@echo "   make invoke-hello_world          # Invocar lambda"
	@echo ""

all-verbose: ## Pipeline completo + tests verbosos (RUN=both)
	@echo "Ejecutando pipeline completo con tests verbosos..."
	@$(MAKE) --no-print-directory RUN=both up package-all deploy list-lambdas run-suite
	@$(MAKE) --no-print-directory test-integration-verbose
	@echo "✅ Pipeline verbose completado"

all-down: ## Pipeline completo + apagar LocalStack
	@$(MAKE) --no-print-directory all
	@$(MAKE) --no-print-directory down

all-nuke: ## Destruir todo (infra + LocalStack)
	@echo "💣 Destruyendo todo..."
	@$(MAKE) --no-print-directory nuke
	@$(MAKE) --no-print-directory down
	@echo "✅ Destrucción total completada"

# =========================
# EOF
# =========================