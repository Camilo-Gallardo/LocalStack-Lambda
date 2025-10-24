# =============================================================================
# 🚀 LocalStack Lambda CI/CD Pipeline
# =============================================================================
# Makefile para desarrollo, testing y deployment de AWS Lambdas en LocalStack
# Incluye: auto-discovery, mock injection, security scanning, y más
# =============================================================================

# =========================
# 🔧 Configuración Base
# =========================
SHELL := /bin/bash
.DEFAULT_GOAL := help

# AWS Configuration
AWS_ENDPOINT ?= http://localhost:4566
REGION       ?= us-east-1

# Python & Tools
PY     := $(shell command -v python3)
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

# Auto-discovery de lambdas
LAMBDA_DIRS := $(shell find lambdas -mindepth 1 -maxdepth 1 -type d -printf "%f\n" 2>/dev/null | sort)
REQ_FILES   := $(shell find lambdas -mindepth 2 -maxdepth 2 -name requirements.txt 2>/dev/null | sort)

# Test suite selector
RUN ?= smoke
SMOKE_SINCE ?= 5
LOG_WINDOW ?= 60

# Directories
SCRIPTS_DIR := scripts
LOGS_DIR    := logs
REPORTS_DIR := reports

# =========================
# 📚 Ayuda
# =========================
.PHONY: help
help: ## 📖 Muestra esta ayuda
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🚀 LocalStack Lambda CI/CD Pipeline                         ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "📋 Comandos disponibles:"
	@echo ""
	@grep -E '^[a-zA-Z0-9_.-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "💡 Ejemplos de uso:"
	@echo "  make all                  # Pipeline completo"
	@echo "  make up deploy            # Solo deploy"
	@echo "  make invoke-hello_world   # Invocar lambda específica"
	@echo "  make logs-hello_world     # Ver logs de lambda"
	@echo ""

# =========================
# 🔨 Bootstrap & Setup
# =========================
.PHONY: bootstrap
bootstrap: ## 🔨 Instala herramientas de desarrollo
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🔧 Instalando dependencias...                               ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@if ! command -v zip &> /dev/null; then \
		echo "⚠️  'zip' no encontrado, instalando..."; \
		sudo apt-get update && sudo apt-get install -y zip || \
		(echo "❌ Error: No se pudo instalar 'zip'. Instálalo manualmente: sudo apt install zip" && exit 1); \
	fi
	@$(PY) -m pip install --upgrade pip --quiet
	@$(PY) -m pip install -r dev-requirements.txt --quiet
	@if command -v pre-commit &> /dev/null; then pre-commit install; fi
	@echo "✅ Bootstrap completo"
	@echo ""

.PHONY: ensure-dirs
ensure-dirs: ## 📁 Crea directorios necesarios
	@mkdir -p $(LOGS_DIR) $(REPORTS_DIR)

# =========================
# 🐳 LocalStack Management
# =========================
.PHONY: up down restart status
up: ## 🐳 Levanta LocalStack
	@echo "🐳 Iniciando LocalStack..."
	@docker compose up -d
	@echo "✅ LocalStack corriendo en $(AWS_ENDPOINT)"

down: ## 🛑 Apaga LocalStack
	@echo "🛑 Deteniendo LocalStack..."
	@docker compose down -v
	@echo "✅ LocalStack detenido"

restart: down up ## 🔄 Reinicia LocalStack

status: ## 📊 Estado de LocalStack
	@echo "📊 Estado de contenedores:"
	@docker compose ps

# =========================
# 🧹 Limpieza
# =========================
.PHONY: clean clean-all
clean: ## 🧹 Limpia archivos generados
	@echo "🧹 Limpiando archivos generados..."
	@find lambdas -name "dist.zip" -delete 2>/dev/null || true
	@find lambdas -name "mock_config.json" -delete 2>/dev/null || true
	@rm -f .lambdas_discovered.json .test_results.json
	@rm -rf $(LOGS_DIR)/* $(REPORTS_DIR)/* 2>/dev/null || true
	@if [ -d .localstack ]; then \
		if [ -w .localstack ]; then \
			rm -rf .localstack; \
		else \
			sudo rm -rf .localstack; \
		fi \
	fi
	@echo "✅ Limpieza completa"

clean-all: clean down ## 🧹💣 Limpieza total (incluye LocalStack)
	@echo "✅ Limpieza total completada"

# =========================
# 🔍 Auto-Discovery
# =========================
.PHONY: discover
discover: ## 🔍 Auto-descubre lambdas
	@echo "🔍 Auto-descubriendo lambdas..."
	@$(PY) testing/auto_discovery.py

# =========================
# 🤖 Mock Configuration
# =========================
.PHONY: generate-mock-configs
generate-mock-configs: discover ## 🤖 Genera mock_config.json automáticamente
	@$(PY) testing/generate_mock_configs.py

# =========================
# 📦 Empaquetado
# =========================
.PHONY: package-% package-all
package-%: ## 📦 Empaqueta lambda específica (ej: package-hello_world)
	@echo "📦 Empaquetando lambda: $*"
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh $*

package-all: discover ## 📦 Empaqueta todas las lambdas
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  📦 Empaquetando todas las lambdas...                        ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@PYTHON=$(PY) $(SCRIPTS_DIR)/package_all_lambdas.sh
	@echo ""
	@echo "✅ Lambdas empaquetadas:"
	@for dir in $(LAMBDA_DIRS); do echo "   ✓ $$dir"; done
	@echo ""

# =========================
# 🏗️  Terraform / Infrastructure
# =========================
.PHONY: plan deploy nuke
plan: ## 🔍 Terraform plan (preview de cambios)
	@echo "🔍 Ejecutando terraform plan..."
	@cd infra/terraform && $(TF) init -upgrade && $(TF) plan

deploy: ## 🚀 Despliega infraestructura a LocalStack
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🚀 Desplegando a LocalStack...                              ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@cd infra/terraform && $(TF) init -upgrade && $(TF) apply -auto-approve
	@echo ""
	@echo "✅ Deployment completado"
	@echo ""

nuke: ## 💣 Destruye toda la infraestructura
	@echo "💣 Destruyendo infraestructura..."
	@cd infra/terraform && $(TF) init -upgrade && $(TF) destroy -auto-approve || true
	@echo "✅ Infraestructura destruida"

# =========================
# 🧪 Tests Automáticos
# =========================
.PHONY: test-auto
test-auto: ensure-dirs ## 🧪 Tests automáticos de integración + mocks
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🧪 Ejecutando tests automáticos...                          ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@$(PY) testing/auto_test_runner.py || true
	@echo ""
	@echo "📋 Guardando logs de lambdas..."
	@names=$$(cat .lambdas_discovered.json | jq -r '.[].name' 2>/dev/null); \
	for fn in $$names; do \
	  echo "   📄 $$fn..."; \
	  $(PY) $(SCRIPTS_DIR)/tail_logs.py \
	    --log-group "/aws/lambda/$$fn" \
	    --since-seconds 300 \
	    --output-file "$(LOGS_DIR)/$$fn.log" \
	    --max-bytes 2000000 \
	    --backup-count 5 2>/dev/null || echo "   ⚠️  Sin logs"; \
	done
	@echo "✅ Logs guardados en $(LOGS_DIR)/"
	@echo ""

# =========================
# 🔥 Smoke Tests
# =========================
.PHONY: list-lambdas smoke
list-lambdas: ## 📋 Lista lambdas desplegadas
	@echo "📋 Lambdas desplegadas:"
	@cd infra/terraform && $(TF) output -json lambda_names 2>/dev/null | jq -r '.[]' | \
		awk '{print "   ✓ " $$0}' || echo "   ⚠️  Ejecuta 'make deploy' primero"

smoke: ensure-dirs ## 🔥 Smoke tests (invoca todas las lambdas)
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🔥 Ejecutando smoke tests...                                ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@$(MAKE) --no-print-directory smoke-execute

.PHONY: smoke-execute
smoke-execute:
	@names=$$(cd infra/terraform && $(TF) output -json lambda_names 2>/dev/null | jq -r '.[]'); \
	if [ -z "$$names" ] || [ "$$names" = "null" ]; then \
	  echo "⚠️  No hay output de Terraform, usando lambdas descubiertas..."; \
	  names=$$(cat .lambdas_discovered.json | jq -r '.[].name' 2>/dev/null); \
	fi; \
	for fn in $$names; do \
	  echo ""; \
	  echo "==> Invoke $$fn"; \
	  "$(PY)" "$(SCRIPTS_DIR)/invoke.py" --function "$$fn" --payload '{"name":"Smoke"}' || exit 1; \
	  echo "==> Logs $$fn (last $(LOG_WINDOW)s)"; \
	  "$(PY)" "$(SCRIPTS_DIR)/tail_logs.py" \
	    --log-group "/aws/lambda/$$fn" \
	    --since-seconds "$(LOG_WINDOW)" \
	    --output-file "$(LOGS_DIR)/$$fn.log" \
	    --max-bytes "2000000" \
	    --backup-count "5" || true; \
	done

# =========================
# 📞 Invocación Manual
# =========================
.PHONY: invoke-% invoke
invoke-%: ## 📞 Invoca lambda específica (ej: invoke-hello_world)
	@echo "📞 Invocando lambda: $*"
	@$(PY) $(SCRIPTS_DIR)/invoke.py --function $* --payload '{"name":"Manual Test"}'

invoke: ## 📞 Invoca lambda custom: FN=nombre PAYLOAD='{"k":"v"}'
	@if [ -z "$(FN)" ]; then \
		echo "❌ Error: Especifica FN=nombre_lambda"; \
		echo "   Ejemplo: make invoke FN=hello_world PAYLOAD='{\"test\":true}'"; \
		exit 1; \
	fi
	@echo "📞 Invocando $(FN)..."
	@$(PY) $(SCRIPTS_DIR)/invoke.py --function "$(FN)" --payload '$(PAYLOAD)'

# =========================
# 📜 Logs
# =========================
.PHONY: logs-% logs-follow-% logs-quick-%
logs-%: ensure-dirs ## 📜 Ver logs de lambda (ej: logs-hello_world)
	@echo "📜 Obteniendo logs de $*..."
	@rm -f $(LOGS_DIR)/$*.log
	@$(PY) $(SCRIPTS_DIR)/tail_logs.py \
		--log-group /aws/lambda/$* \
		--since-seconds $(SMOKE_SINCE) \
		--output-file $(LOGS_DIR)/$*.log \
		--max-bytes 2000000 \
		--backup-count 5 || true
	@echo "✅ Logs guardados en $(LOGS_DIR)/$*.log"

logs-follow-%: ensure-dirs ## 📜🔄 Sigue logs en tiempo real (ej: logs-follow-hello_world)
	@echo "📜🔄 Siguiendo logs de $* en tiempo real..."
	@$(PY) $(SCRIPTS_DIR)/tail_logs.py \
		--log-group /aws/lambda/$* \
		--follow \
		--idle-exit 15 \
		--max-seconds 300 \
		--output-file $(LOGS_DIR)/$*.log || true

logs-quick-%: ensure-dirs ## 📜⚡ Ver últimos logs (30s) (ej: logs-quick-hello_world)
	@echo "📜⚡ Logs rápidos de $*..."
	@$(PY) $(SCRIPTS_DIR)/tail_logs.py \
		--log-group /aws/lambda/$* \
		--follow \
		--since-seconds 30 \
		--idle-exit 5 \
		--max-seconds 60 \
		--output-file $(LOGS_DIR)/$*.log || true

# =========================
# 🧪 Tests Tradicionales
# =========================
.PHONY: test-unit test-integration test-integration-verbose
test-unit: ## 🧪 Unit tests
	@echo "🧪 Ejecutando unit tests..."
	@$(PYTEST) -q tests/unit

test-integration: ## 🧪 Tests de integración
	@echo "🧪 Ejecutando tests de integración..."
	@$(PYTEST) -q --no-cov tests/integration

test-integration-verbose: ## 🧪 Tests de integración (verbose)
	@echo "🧪 Ejecutando tests de integración (verbose)..."
	@$(PYTEST) -vv -s --no-cov -rA --durations=5 tests/integration

# =========================
# 🎯 Suite Selector
# =========================
.PHONY: run-suite
run-suite: ## 🎯 Ejecuta suite de tests (RUN=smoke|tests|all)
	@echo "🎯 Ejecutando suite: $(RUN)"
	@if [ "$(RUN)" = "tests" ]; then \
	  $(MAKE) --no-print-directory test-integration; \
	elif [ "$(RUN)" = "smoke" ]; then \
	  $(MAKE) --no-print-directory smoke; \
	else \
	  $(MAKE) --no-print-directory test-integration && $(MAKE) --no-print-directory smoke; \
	fi

# =========================
# 🔒 Security Scanning
# =========================
.PHONY: security-scan
security-scan: ensure-dirs ## 🔒 Análisis de seguridad (Bandit + pip-audit)
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🔒 Ejecutando análisis de seguridad...                      ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@bandit -r lambdas -f json -o $(REPORTS_DIR)/bandit_report.json --quiet || true
	@echo "" > $(REPORTS_DIR)/pip_audit_report.txt
	@for f in $(REQ_FILES); do \
	  echo "==> pip-audit $$f"; \
	  echo "=== Auditing $$f ===" >> $(REPORTS_DIR)/pip_audit_report.txt; \
	  pip-audit -r "$$f" >> $(REPORTS_DIR)/pip_audit_report.txt 2>&1 || true; \
	  echo "" >> $(REPORTS_DIR)/pip_audit_report.txt; \
	done
	@$(PY) $(SCRIPTS_DIR)/security_console_report.py || true
	@echo ""
	@echo "✅ Reportes de seguridad guardados:"
	@echo "   📄 Bandit:       $(REPORTS_DIR)/bandit_report.json"
	@echo "   📄 pip-audit:    $(REPORTS_DIR)/pip_audit_report.txt"
	@echo "   📄 Consolidado:  $(REPORTS_DIR)/security_console_report.json"
	@echo ""

# =========================
# 🚀 Pipeline Completo
# =========================
.PHONY: all all-down all-nuke
all: ensure-dirs ## 🚀 Pipeline CI/CD completo
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🚀 PIPELINE CI/CD COMPLETO                                  ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@$(MAKE) --no-print-directory up
	@$(MAKE) --no-print-directory discover
	@$(MAKE) --no-print-directory generate-mock-configs
	@$(MAKE) --no-print-directory package-all
	@$(MAKE) --no-print-directory deploy
	@$(MAKE) --no-print-directory list-lambdas
	@$(MAKE) --no-print-directory test-auto
	@$(MAKE) --no-print-directory run-suite
	@$(MAKE) --no-print-directory security-scan
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  ✅ PIPELINE COMPLETADO                                      ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "📊 Reportes generados:"
	@echo "   🔒 Security:     $(REPORTS_DIR)/security_console_report.json"
	@echo "   🐛 Bandit:       $(REPORTS_DIR)/bandit_report.json"
	@echo "   📦 pip-audit:    $(REPORTS_DIR)/pip_audit_report.txt"
	@echo "   🧪 Tests:        .test_results.json"
	@echo "   📜 Logs:         $(LOGS_DIR)/*.log"
	@echo ""
	@echo "💡 Comandos útiles:"
	@echo "   make logs-hello_world    # Ver logs de una lambda"
	@echo "   make invoke-hello_world  # Invocar una lambda"
	@echo "   make report              # Ver reporte consolidado"
	@echo ""

all-down: all ## 🚀🛑 Pipeline completo + apagar LocalStack
	@$(MAKE) --no-print-directory down

all-nuke: ## 💣 Destruir todo (infra + LocalStack + archivos)
	@echo "💣 Destruyendo todo..."
	@$(MAKE) --no-print-directory nuke
	@$(MAKE) --no-print-directory down
	@$(MAKE) --no-print-directory clean
	@echo "✅ Destrucción total completada"

# =========================
# 📊 Reportes
# =========================
.PHONY: report
report: ## 📊 Genera reporte consolidado
	@echo "📊 Generando reporte final..."
	@$(PY) testing/report_generator.py

# =========================
# 🎨 Shortcuts útiles
# =========================
.PHONY: dev quick
dev: up deploy ## 🎨 Setup rápido de desarrollo (up + deploy)
	@echo "✅ Entorno de desarrollo listo"

quick: deploy smoke ## ⚡ Deploy + smoke tests rápido
	@echo "✅ Deploy y smoke tests completados"

# =========================
# EOF
# =========================
