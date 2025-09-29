SHELL := /bin/bash
AWS_ENDPOINT=http://localhost:4566
REGION=us-east-1

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?##' Makefile | sort | awk 'BEGIN {FS = ":.*?##"}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Instala herramientas de desarrollo
	pip install -r dev-requirements.txt
	pre-commit install

up: ## Levanta LocalStack
	docker compose up -d

down: ## Apaga LocalStack
	docker compose down -v

package-hello: ## Empaqueta lambda hello_world
	cd lambdas/hello_world && bash build.sh

plan: ## Terraform plan contra LocalStack
	cd infra/terraform && terraform init && terraform plan

deploy: package-hello ## Despliega recursos a LocalStack
	cd infra/terraform && terraform init -upgrade && terraform apply -auto-approve

nuke: ## Elimina recursos
	cd infra/terraform && terraform destroy -auto-approve || true

test-unit: ## Ejecuta tests unitarios
	pytest -q tests/unit

test-integration: ## Ejecuta tests de integración contra LocalStack (sin cobertura)
	pytest -q --no-cov tests/integration

security-scan: ## Scanners de seguridad (código y dependencias)
	bandit -q -r lambdas -f txt || true
	pip-audit -r lambdas/hello_world/requirements.txt || true

invoke-hello: ## Invoca la Lambda hello_world en LocalStack
	python scripts/invoke_hello.py


# Últimos 120s y sale, guardando en logs/hello_world.log con rotación
logs-hello: ## Muestra últimos logs (120s) y los guarda con rotación
	python scripts/tail_logs.py --since-seconds 120 --output-file logs/hello_world.log --max-bytes 2000000 --backup-count 5 || true

# Sigue en vivo, corta si no hay nuevos eventos por 15s o a los 5 min máx; guarda en archivo
logs-hello-follow: ## Sigue logs y corta solo (idle=15s, max=300s), guarda con rotación
	python scripts/tail_logs.py --follow --since-seconds 60 --idle-exit 15 --max-seconds 300 --output-file logs/hello_world.log || true

# Tail rápido, corta por inactividad 5s o 60s máx; guarda en archivo
logs-hello-quick: ## Sigue logs y corta si no hay eventos por 5s (máx 60s), guarda con rotación
	python scripts/tail_logs.py --follow --since-seconds 30 --idle-exit 5 --max-seconds 60 --output-file logs/hello_world.log || true




