# LocalStack Lambda Test Environment

Ambiente reproducible para **probar funciones AWS Lambda en local**, con:

* **LocalStack** (emula servicios AWS),
* **Terraform** (infra como código),
* **Pytest** (tests unitarios e integración),
* **Escáneres de seguridad** (Bandit, pip-audit),
* **Automatizaciones con Make**,
* **Tail de logs** con script propio (rotación y auto-stop).

> **Objetivo:** que cualquier persona pueda clonar, levantar el entorno, desplegar una Lambda de ejemplo, **probarla automáticamente** y revisar logs **sin instalar AWS** ni crear recursos reales.

---

## Índice

1. [Arquitectura y flujo](#arquitectura-y-flujo)
2. [Estructura del repo](#estructura-del-repo)
3. [Requisitos](#requisitos)
4. [Instalación y primer arranque](#instalación-y-primer-arranque)
5. [Comandos Make (guía rápida)](#comandos-make-guía-rápida)
6. [Servicios y herramientas usadas](#servicios-y-herramientas-usadas)
7. [Cómo funciona cada pieza](#cómo-funciona-cada-pieza)

   * [LocalStack](#localstack)
   * [Terraform](#terraform)
   * [Lambda (packaging y handler)](#lambda-packaging-y-handler)
   * [Testing](#testing)
   * [Seguridad](#seguridad)
   * [Logs y observabilidad](#logs-y-observabilidad)
8. [Extender el proyecto](#extender-el-proyecto)
9. [Solución de problemas comunes](#solución-de-problemas-comunes)
10. [Buenas prácticas y siguientes pasos](#buenas-prácticas-y-siguientes-pasos)
11. [FAQ](#faq)

---

## Arquitectura y flujo

```
┌────────────┐   make   ┌────────────┐   terraform   ┌──────────────┐
│  Desarroll│──────────▶│  Packaging │──────────────▶│  LocalStack  │
│   ador    │           │   (ZIP)    │               │ (AWS emulado)│
└────────────┘          └────────────┘               └──────┬───────┘
         ▲                         │                           │
         │        pytest (unit)    │                           │
         │        pytest (integ)   │  boto3 invoke/logs        │
         └─────────────────────────┴───────────────────────────┘
```

* **Local**: editas código, empaquetas (`dist.zip`), despliegas con Terraform a **LocalStack**, ejecutas **tests** (unit e integración), ves **logs**.
* **Sin AWS real**: LocalStack emula Lambda, CloudWatch Logs, IAM, STS, S3, API Gateway, EventBridge, etc.

---

## Estructura del repo

```
localstack-lambda-lab/
├─ docker-compose.yml              # LocalStack
├─ Makefile                        # Automatizaciones
├─ README.md                       # Este documento
├─ pyproject.toml                  # Config de pytest/formatters
├─ .pre-commit-config.yaml         # Hooks de calidad
├─ .gitignore
├─ dev-requirements.txt            # Dependencias de dev
├─ infra/
│  └─ terraform/
│     ├─ main.tf                   # Provider AWS y endpoints a LocalStack
│     ├─ variables.tf
│     ├─ iam.tf                    # Rol básico para Lambda
│     ├─ lambda_hello.tf           # Recurso Lambda de ejemplo
│     └─ outputs.tf
├─ lambdas/
│  └─ hello_world/
│     ├─ src/handler.py            # Código Lambda
│     ├─ requirements.txt          # Deps runtime (si aplica)
│     └─ build.sh                  # Empaquetado a dist.zip
├─ scripts/
│  ├─ invoke_hello.py              # Invocación de Lambda vía boto3
│  └─ tail_logs.py                 # Tail de logs con rotación y auto-stop
└─ tests/
   ├─ unit/test_hello_unit.py      # Tests unitarios
   └─ integration/test_hello_integration.py # Tests integración (LocalStack)
```

---

## Requisitos

* **Docker** y **Docker Compose** (últimas versiones)
* **Python 3.11+** (sugerido)
* **make**
* **Terraform 1.5+** (instalado o en Docker/alias)
* (Opcional) **AWS CLI** / **awscli-local** (no obligatorio si usas scripts Python)

> **Tip Linux**: crea venv en una ruta **sin espacios** para evitar problemas con shebangs (`~/.venvs/ls-lab`).

---

## Instalación y primer arranque

```bash
# 1) Clonar el repo
git clone <tu_repo>.git
cd localstack-lambda-lab

# 2) Entorno Python
python -m venv .venv
source .venv/bin/activate
pip install -r dev-requirements.txt

# 3) Levantar LocalStack
make up

# 4) Empaquetar Lambda de ejemplo
make package-hello

# 5) Desplegar infraestructura a LocalStack (Terraform init + apply)
make deploy

# 6) Probar:
make invoke-hello         # Invocación directa con boto3
make test-unit            # Tests unitarios (cobertura local)
make test-integration     # Tests de integración (LocalStack)

# 7) Ver logs (últimos 120s y sale)
make logs-hello
```

---

## Comandos Make (guía rápida)

| Comando                  | Descripción                                              |
| ------------------------ | -------------------------------------------------------- |
| `make up`                | Levanta LocalStack (docker compose)                      |
| `make down`              | Apaga y limpia contenedores                              |
| `make package-hello`     | Empaqueta la Lambda `hello_world` a `dist.zip`           |
| `make plan`              | `terraform init && plan` contra LocalStack               |
| `make deploy`            | `terraform init -upgrade && apply -auto-approve`         |
| `make nuke`              | `terraform destroy -auto-approve`                        |
| `make test-unit`         | Ejecuta tests unitarios con cobertura (local)            |
| `make test-integration`  | Ejecuta tests de integración (LocalStack, sin cobertura) |
| `make security-scan`     | Bandit + pip-audit (código y dependencias)               |
| `make invoke-hello`      | Invoca la Lambda `hello_world` con boto3                 |
| `make logs-hello`        | Imprime últimos logs (120s) y termina                    |
| `make logs-hello-follow` | Tail vivo con auto-stop por inactividad o tiempo máx     |
| `make logs-hello-quick`  | Tail rápido (ventanas cortas)                            |

> Ejecuta `make help` para ver descripciones embebidas.

---

## Servicios y herramientas usadas

* **LocalStack**: emula AWS (Lambda, CloudWatch Logs, IAM, STS, S3, API Gateway, Events).
* **Terraform**: define y despliega recursos en LocalStack.
* **Pytest**: framework de pruebas (unitarias/integración).
* **boto3**: SDK AWS para Python, se usa en tests/invocaciones.
* **Bandit / pip-audit / detect-secrets**: seguridad.
* **pre-commit**: formateo (Black, isort), linting (flake8) y escaneo de secretos.

---

## Cómo funciona cada pieza

### LocalStack

* **`docker-compose.yml`** ejecuta `localstack/localstack` y expone **puerto 4566** (edge).
* Variables:

  * `SERVICES=lambda,logs,iam,sts,cloudwatch,events,apigateway,s3`
  * `LAMBDA_EXECUTOR=docker-reuse` (rápido para desarrollo)
  * `PERSISTENCE=1` (estado persistente en `.localstack/`)
* Monta `docker.sock` para ejecutar runtimes de Lambda en contenedores.

### Terraform

* **Provider AWS v5** apuntando a LocalStack con `endpoints` y flags:

  ```hcl
  provider "aws" {
    region                     = var.region
    s3_use_path_style          = true
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    endpoints { ... http://localhost:4566 ... }
  }
  ```
* Recursos:

  * **IAM role** básico para Lambda.
  * **CloudWatch Log Group** `/aws/lambda/hello_world`.
  * **Lambda** `hello_world` con `runtime=python3.11`, `handler=handler.handler`, `environment` (p.ej. `STAGE=local`).

### Lambda (packaging y handler)

* **Packaging** (`lambdas/hello_world/build.sh`):

  * Instala dependencias de `requirements.txt` en `build/python` (patrón de layer compatible).
  * Copia `src/*` a `build/`.
  * Empaqueta `build/` → `dist.zip` (usado por Terraform).
* **Handler** (`src/handler.py`):

  * Retorna un JSON con `ok`, `message` y `stage`.
  * Soporta invocación directa con `boto3`.
    *(Si se integra API Gateway, puede incluir rama para proxy events).*

### Testing

* **Unit tests**:

  * Importan el handler directamente.
  * Verifican lógica de negocio pura (sin AWS).
  * **Cobertura**: configurada en `pyproject.toml` (`--cov-fail-under=80`).
* **Integration tests**:

  * Ejecutan contra LocalStack con `boto3` (invocación real).
  * **Sin cobertura** (`--no-cov`) porque el código corre en otro proceso (no instrumentable localmente).

### Seguridad

* **Bandit**: análisis estático (buenas prácticas y patrones de riesgo).
* **pip-audit**: CVEs en dependencias de `requirements.txt`.
* **detect-secrets**: (pre-commit) evita subir credenciales.

### Logs y observabilidad

* `scripts/tail_logs.py` usa `boto3` contra **CloudWatch Logs** en LocalStack:

  * Modo “pasada única” o “follow”.
  * **Auto-stop** por inactividad y/o tiempo máximo.
  * **Rotación** a archivo (`logs/hello_world.log`) con backups configurables.

---

## Extender el proyecto

### Agregar una nueva Lambda

1. Crea carpeta `lambdas/<mi_lambda>/` con:

   * `src/handler.py`
   * `requirements.txt`
   * `build.sh` (puedes copiar el existente)
2. Añade un `.tf` en `infra/terraform/` (p.ej. `lambda_mi_lambda.tf`) apuntando al ZIP `lambdas/<mi_lambda>/dist.zip`.
3. Crea tests:

   * `tests/unit/test_mi_lambda_unit.py`
   * `tests/integration/test_mi_lambda_integration.py`
4. Opcional: añade `package-mi-lambda` al `Makefile` para empaquetado específico.

### Exponer por API Gateway (REST)

* Añade recursos `aws_api_gateway_*` + `aws_lambda_permission` y un `deployment`.
* Construye URL de invocación `http://localhost:4566/restapis/{apiId}/{stage}/_user_request_/path`.

### Flujos asíncronos

* **SQS/SNS/EventBridge**: crea recursos en Terraform y tests que publiquen eventos y verifiquen efectos.

### CI/CD (GitHub Actions)

* Servicio LocalStack como `services:` en el job.
* Steps: instalar deps, `make package-*`, instalar Terraform, `make deploy`, `make test-*`.

---

## Solución de problemas comunes

**`make: *** falta un separador`**

* Las líneas de comandos en el `Makefile` **deben** comenzar con **TAB**, no espacios.

**`terraform: command not found`**

* Instala Terraform o usa alias Docker:

  ```bash
  alias terraform='docker run --rm -it -v "$PWD":/workspace -w /workspace --network host -u $(id -u):$(id -g) hashicorp/terraform:1.9.5'
  ```

**`Unsupported argument: s3_force_path_style`**

* En provider AWS v5 es `s3_use_path_style`.

**Heredoc en `make invoke-hello` no cierra**

* Evita heredocs en Make (sensibles a TAB). Usa el script `scripts/invoke_hello.py`.

**`awslocal` falla / shebang con espacios en ruta**

* Solución rápida:

  ```bash
  python "$(which awslocal)" <comando aws...>
  ```

  o cambia la primera línea de `.venv/bin/awslocal` a `#!/usr/bin/env python3`, o usa el **script con boto3** (recomendado).

**Cobertura 0% en integración**

* Normal: el código corre en LocalStack (otro proceso). Se desactiva con `--no-cov` para tests de integración.

---

## Buenas prácticas y siguientes pasos

* **Pirámide de pruebas**: más unitarias que integración; e2e solo para flujos críticos.
* **Principio de mínimos privilegios**: ajustar políticas IAM (y escanear IaC con Checkov si añades más recursos).
* **Layers**: mover dependencias pesadas a layers para acelerar empaquetado/despliegue.
* **CI en PRs**: todo PR debería correr `package -> deploy(LocalStack) -> tests -> security`.
* **Observabilidad**: estandariza logs JSON y IDs de correlación si agregas más servicios.

---

## FAQ

**¿Esto usa AWS real?**
No. Todo corre en **LocalStack**, de forma local, sin costos.

**¿Puedo usar Node.js/Go/Java?**
Sí. Replica el patrón: `build.sh` para empaquetar, `runtime/handler` adecuados y ajusta tests.

**¿Cómo actualizo LocalStack?**
Edita `docker-compose.yml` con la versión deseada y `make down && make up`.

**¿Se puede probar API Gateway, SQS, SNS, EventBridge?**
Sí. Agrega los recursos en Terraform y tests de integración; LocalStack los soporta.

---

### Créditos / Licencia

* Este repo es una plantilla didáctica para equipos que trabajan con AWS Lambda y buscan **ciclos de feedback rápidos** en local.
* Licencia sugerida: MIT (ajústalo a las políticas de tu empresa).

---

## Anexos (snippets clave)

**Empaquetado (build.sh)**

```bash
#!/usr/bin/env bash
set -euo pipefail
rm -rf build dist.zip
mkdir -p build/python
pip install -r requirements.txt -t build/python
cp -r src/* build/
cd build && zip -r ../dist.zip . >/dev/null && cd -
```

**Invocación (scripts/invoke_hello.py)**

```python
import json, boto3, os
AWS_ENDPOINT = os.environ.get("AWS_ENDPOINT","http://localhost:4566")
REGION = os.environ.get("REGION","us-east-1")
client = boto3.client("lambda", endpoint_url=AWS_ENDPOINT, region_name=REGION,
                      aws_access_key_id="test", aws_secret_access_key="test")
resp = client.invoke(FunctionName="hello_world",
                     Payload=json.dumps({"name":"Camilo"}).encode())
print(resp["StatusCode"], resp.get("FunctionError"))
print(resp["Payload"].read().decode())
```

**Tail con rotación (scripts/tail_logs.py)** → *ver sección [Logs y observabilidad](#logs-y-observabilidad)*.

---
