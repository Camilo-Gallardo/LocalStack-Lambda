# LocalStack Lambda Lab (Makefile-First)

Entorno reproducible para **desarrollar y probar Lambdas de AWS en local**, con:

* **LocalStack** (emula servicios AWS),
* **Terraform** (infra como código),
* **Pytest** (unit/integración),
* **Makefile** (pipeline de “un botón”: `make all`),
* **Tail de logs** con rotación,
* **Scanners de seguridad** (Bandit, pip-audit).

> **Objetivo**: clonas el repo, corres `make all` y en minutos tienes Lambdas empaquetadas, desplegadas en LocalStack, invocadas, con pruebas y **logs guardados en archivos** — sin tocar AWS real.

---

## Índice

1. [Arquitectura y flujo](#arquitectura-y-flujo)
2. [Estructura del repo](#estructura-del-repo)
3. [Requisitos](#requisitos)
4. [Instalación y primer arranque](#instalación-y-primer-arranque)
5. [Comandos Make (guía rápida)](#comandos-make-guía-rápida)
6. [Parámetros útiles (RUN, SMOKE_SINCE, LOG_WINDOW)](#parámetros-útiles-run-smoke_since-log_window)
7. [Cómo funciona cada pieza](#cómo-funciona-cada-pieza)
8. [Extender el proyecto](#extender-el-proyecto)
9. [Notas importantes sobre logs “Smoke”](#notas-importantes-sobre-logs-smoke)
10. [Solución de problemas](#solución-de-problemas)
11. [Buenas prácticas y siguientes pasos](#buenas-prácticas-y-siguientes-pasos)
12. [FAQ](#faq)

---

## Arquitectura y flujo

```
┌──────────┐  make/package  ┌────────────┐   terraform   ┌──────────────┐
│ Dev local│ ─────────────▶ │   ZIP(s)   │ ─────────────▶│  LocalStack  │
└────▲─────┘                └─────┬──────┘               └──────┬───────┘
     │ pytest (unit/integration)  │  boto3 invoke/logs           │
     └────────────────────────────┴───────────────────────────────┘
```

* Editas código → `build.sh` empaqueta cada Lambda a `dist.zip`.
* Terraform despliega a **LocalStack** (Lambda, IAM, CloudWatch Logs, etc.)
* Tests de integración invocan Lambdas reales (emuladas).
* **Smoke** invoca y guarda logs en `logs/*.log` con rotación.

---

## Estructura del repo

```
localstack-lambda-lab/
├─ docker-compose.yml
├─ Makefile
├─ README.md
├─ pyproject.toml
├─ dev-requirements.txt
├─ infra/terraform/
│  ├─ main.tf, variables.tf, iam.tf
│  ├─ lambda_*.tf                 # recursos Lambda
│  └─ outputs.tf                  # lista de lambdas: lambda_names
├─ lambdas/
│  ├─ hello_world/
│  │  ├─ src/handler.py
│  │  ├─ requirements.txt
│  │  └─ build.sh                 # genera dist.zip
│  └─ greeter/ ...
├─ scripts/
│  ├─ invoke.py                   # invoca cualquier Lambda
│  └─ tail_logs.py                # tail CloudWatch (rotación y límites)
└─ tests/
   ├─ unit/...
   └─ integration/
      ├─ test_all_lambdas.py      # parametriza sobre lambda_names
      └─ test_hello_integration.py
```

---

## Requisitos

* **Docker** + **Docker Compose**
* **Python 3.11+**
* **make**
* **Terraform 1.9.x** (instalado o se usa la imagen oficial automáticamente)
* (Opcional) AWS CLI

> El Makefile detecta `terraform` local o usa `hashicorp/terraform:1.9.5` en Docker con `--network host`.

---

## Instalación y primer arranque

```bash
git clone <tu_repo>.git
cd localstack-lambda-lab

python -m venv .venv
source .venv/bin/activate
pip install -r dev-requirements.txt

# Pipeline completo, por defecto RUN=smoke:
make all

# Variante “todo + tests verbosos”
make all-verbose
```

---

## Comandos Make (guía rápida)

### Core

| Comando             | Descripción                                                         |
| ------------------- | ------------------------------------------------------------------- |
| `make up`           | Levanta LocalStack (`docker compose up -d`).                        |
| `make down`         | Apaga LocalStack y limpia volúmenes.                                |
| `make package-%`    | Empaqueta la Lambda `%` (ej: `package-hello_world`).                |
| `make package-all`  | Empaqueta **todas** las Lambdas (carpetas en `lambdas/`).           |
| `make plan`         | `terraform init && plan` contra LocalStack.                         |
| `make deploy`       | `terraform init -upgrade && apply -auto-approve` (no re-empaqueta). |
| `make nuke`         | `terraform destroy -auto-approve` (con `init -upgrade`).            |
| `make list-lambdas` | Lista nombres de Lambdas desde `terraform output lambda_names`.     |

### Invocación y logs

| Comando                                  | Descripción                                                           |
| ---------------------------------------- | --------------------------------------------------------------------- |
| `make invoke-%`                          | Invoca Lambda `%` con payload de ejemplo.                             |
| `make invoke FN=... PAYLOAD='{"k":"v"}'` | Invocación arbitraria.                                                |
| `make logs-%`                            | Guarda en `logs/%.log` los **últimos N s** (usa `SMOKE_SINCE`).       |
| `make logs-follow-%`                     | Tail “follow” (corta por inactividad o max time).                     |
| `make logs-quick-%`                      | Tail rápido (ventanas cortas).                                        |
| `make smoke`                             | Invoca **todas** las Lambdas y guarda logs recientes en `logs/*.log`. |

### Tests

| Comando                         | Descripción                              |
| ------------------------------- | ---------------------------------------- |
| `make test-unit`                | Unit tests (local, cobertura).           |
| `make test-integration`         | Integración (LocalStack, sin cobertura). |
| `make test-integration-verbose` | Integración verbosa (prints/duraciones). |

### Pipelines “one-shot”

| Comando            | Descripción                                                                        |
| ------------------ | ---------------------------------------------------------------------------------- |
| `make all`         | `up → package-all → deploy → list-lambdas → run-suite` (por defecto `RUN=smoke`).  |
| `make all-verbose` | Igual que `all` pero ejecuta **ambas suites** y además `test-integration-verbose`. |
| `make all-down`    | `make all` y luego `down`.                                                         |
| `make all-nuke`    | `nuke` + `down`.                                                                   |

> **Tip**: `make help` lista todos los targets con descripción.

---

## Parámetros útiles (`RUN`, `SMOKE_SINCE`, `LOG_WINDOW`)

* `RUN` selecciona qué suite corre en `run-suite`:

  * `RUN=smoke` *(default)* → solo invoca y guarda logs.
  * `RUN=tests` → solo integración.
  * `RUN=both` → integración **y** smoke.

* `SMOKE_SINCE` (segundos): ventana corta para `logs-%` dentro de `smoke`.
  Por defecto 5 s para minimizar arrastre de corridas previas.

* `LOG_WINDOW` (segundos): ventana general para `smoke` si se usa esa variable en lugar de `SMOKE_SINCE` (el Makefile soporta ambos enfoques; por defecto usamos `SMOKE_SINCE` en `smoke`).

Ejemplos:

```bash
make all RUN=both
make smoke SMOKE_SINCE=3
make logs-hello_world SMOKE_SINCE=10
```

---

## Cómo funciona cada pieza

### Packaging de Lambdas

Cada carpeta en `lambdas/<name>/` tiene un `build.sh` que:

* crea `build/` y `build/python`,
* instala `requirements.txt` en `build/python`,
* copia `src/*` a `build/`,
* genera `dist.zip`.

`package-all` descubre automáticamente los módulos por subcarpeta.

### Terraform

* Provider AWS v5 apuntado a `http://localhost:4566` con flags de LocalStack.
* IAM Role básico + CloudWatch Log Groups `/aws/lambda/<fn>` + `aws_lambda_function`.
* `outputs.tf` expone `lambda_names` para listar e iterar (smoke/tests).

### Pruebas

* **Unit**: importan el handler, sin AWS.
* **Integración**: usan **boto3** contra LocalStack; verifican que la Lambda existe e invoca OK (200, `ok=True`), y que el `message` retorne string.

### Logs

* `scripts/tail_logs.py` usa CloudWatch Logs (LocalStack) con:

  * modo “una pasada” o “follow”,
  * **rotación** a `logs/<fn>.log` (`--max-bytes` y `--backup-count`),
  * límites de tiempo/inactividad para evitar quedarse colgado.

---

## Extender el proyecto

1. **Agregar una Lambda**: crea `lambdas/<nueva>/` con `src/`, `requirements.txt`, `build.sh`.
2. **Infra**: añade `infra/terraform/lambda_<nueva>.tf` apuntando a `lambdas/<nueva>/dist.zip`.
3. **Pruebas**: crea `tests/unit/...` y `tests/integration/...`.
4. **Servicios adicionales**: añade `aws_s3_bucket`, `aws_cloudwatch_*`, `aws_sqs_queue`, etc., y cubre con tests.
5. **CI**: monta un pipeline que haga `package → deploy (LocalStack) → tests → smoke → artifacts`.

---

## **Notas importantes sobre logs “Smoke”**

> **Smoke lee los últimos N segundos** (configurable con `SMOKE_SINCE`/`LOG_WINDOW`).
> Si ejecutas `make all` varias veces en menos de **N** segundos, **verás en consola y en los archivos líneas repetidas** que pertenecen a la corrida anterior. **No** son dobles invocaciones; es el mismo evento que sigue dentro de la ventana temporal consultada.

Sugerencias:

* Mantén N pequeño (5–10 s) y deja un `sleep 2–3 s` tras invocar para dar tiempo a que CloudWatch “publique” el log.
* Si quieres traer **solo** la invocación “de esta ronda”, cambia el tail para filtrar desde un timestamp capturado justo antes/tras invocar (requeriría extender `tail_logs.py` para aceptar un `--start-ts` o un patrón de correlación).

---

## Solución de problemas

**No veo archivos en `logs/`**

* Asegúrate de que el target que corre logs **depende** de `ensure-dirs` (el Makefile lo hace).
* Verifica permisos de escritura en la carpeta del repo.
* Revisa consola: `tail_logs.py` imprime el contenido y **también** lo guarda en `logs/<fn>.log` (con rotación). Busca `logs/hello_world.log`.

**“Parece que invoca dos veces”**

* Revisa la [nota de Smoke](#notas-importantes-sobre-logs-smoke): son líneas de la corrida anterior aún dentro de la ventana de tiempo.

**Terraform siempre “modifica”**

* Es normal si el `dist.zip` cambia (hash nuevo). Para evitar “falsos diffs”, procura builds deterministas (timestamps fijos, orden de archivos) o solo empaquetar cuando cambie el código (locks/flags).

**`terraform` no instalado**

* El Makefile usa automáticamente la imagen oficial (Docker). Asegura `docker` corriendo y `--network host` disponible.

**Tests de integración sin cobertura**

* Es lo esperado: la Lambda corre dentro de LocalStack (otro proceso). Por eso `--no-cov`.

---

## Buenas prácticas y siguientes pasos

* **Pirámide de pruebas**: mayoría unitarias; integración solo para contratos con AWS; e2e para flujos críticos.
* **Mocks “behind the scenes”**: para la mayoría de tests, simula AWS (moto/fixtures) y deja LocalStack para pocas integraciones.
* **CI**: pipeline por PR con `make all RUN=both`, subiendo `logs/*.log` y reportes como artifacts.
* **Observabilidad**: estandariza logs JSON + `correlation_id` para trazabilidad; filtra por patrón en tail cuando lo añadamos.
* **Reutilización**: convierte el repo en “harness” invocable desde otros repos, apuntando a su `lambdas/`.

---

## FAQ

**¿Usa AWS real?**
No. Todo corre en **LocalStack**.

**¿Puedo añadir S3/SQS/SNS/API Gateway?**
Sí. Añade recursos Terraform y tests. LocalStack los soporta.

**¿Puedo usar Node.js/Go/Java?**
Sí. Replica el patrón de `build.sh` y ajusta `runtime/handler`.

**¿Cómo ajusto la “ventana” de logs?**
Pasa `SMOKE_SINCE` o `LOG_WINDOW`:
`make smoke SMOKE_SINCE=3` — **menos arrastre** de corridas previas.

---
