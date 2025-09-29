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
	cd infra/terraform && terraform apply -auto-approve


nuke: ## Elimina recursos
	cd infra/terraform && terraform destroy -auto-approve || true


test-unit: ## Ejecuta tests unitarios
	pytest -q tests/unit


test-integration: ## Ejecuta tests de integración contra LocalStack
	pytest -q tests/integration


security-scan: ## Scanners de seguridad (código y dependencias)
	bandit -q -r lambdas -f txt || true
	pip-audit -r lambdas/hello_world/requirements.txt || true


invoke-hello: ## Invoca la Lambda hello_world en LocalStack
	python - <<'PY'
import json, boto3
client=boto3.client('lambda',endpoint_url='$(AWS_ENDPOINT)',region_name='$(REGION)',aws_access_key_id='test',aws_secret_access_key='test')
resp=client.invoke(FunctionName='hello_world',Payload=json.dumps({'name':'Camilo'}).encode())
print(resp['StatusCode'], resp['FunctionError'])
print(resp['Payload'].read().decode())
PY


logs-hello: ## Muestra logs de hello_world
	aws --endpoint-url=$(AWS_ENDPOINT) logs tail /aws/lambda/hello_world --follow --since 1m || true
