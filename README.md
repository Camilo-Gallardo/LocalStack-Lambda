# LocalStack Lambda CI/CD Pipeline

Entorno reproducible para **desarrollar y probar Lambdas de AWS en local**, con:
* **LocalStack** (emula servicios AWS),
* **Terraform** (infra como código),
* **Auto-discovery** (detección automática de lambdas),
* **Mock Injector** (mockea boto3 sin modificar código),
* **Testing automático** (integración + mocks locales),
* **Makefile** (pipeline de "un botón": `make all`),
* **Logs** con rotación automática,
* **Security scanning** (Bandit, pip-audit).

> **Objetivo**: clonas el repo, corres `make all` y en minutos tienes Lambdas auto-descubiertas, empaquetadas, desplegadas en LocalStack, testeadas con mocks, con análisis de seguridad y **logs guardados en archivos** — sin tocar AWS real.

---

## Índice

1. [Arquitectura y flujo](#arquitectura-y-flujo)
2. [Estructura del repo](#estructura-del-repo)
3. [Requisitos](#requisitos)
4. [Instalación y primer arranque](#instalación-y-primer-arranque)
5. [Comandos Make (guía rápida)](#comandos-make-guía-rápida)
6. [Sistema de Mocks](#sistema-de-mocks)
7. [Testing automático](#testing-automático)
8. [Parámetros útiles](#parámetros-útiles)
9. [Cómo funciona cada pieza](#cómo-funciona-cada-pieza)
10. [Security scanning](#security-scanning)
11. [Solución de problemas](#solución-de-problemas)
12. [Buenas prácticas y siguientes pasos](#buenas-prácticas-y-siguientes-pasos)
13. [FAQ](#faq)

---

## Arquitectura y flujo

```
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE CI/CD COMPLETO                      │
└─────────────────────────────────────────────────────────────────┘

  Dev Local
      │
      ├─► Auto-Discovery      → Detecta lambdas automáticamente
      │
      ├─► Mock Generator      → Genera mock_config.json
      │
      ├─► Package             → Empaqueta lambdas con deps
      │
      ├─► Terraform Deploy    → Despliega a LocalStack
      │
      ├─► Auto Tests          → 6 tests por lambda (integración + mocks)
      │   ├─ Deployment ✓
      │   ├─ Invocación ✓
      │   ├─ Formato ✓
      │   ├─ Logs ✓
      │   ├─ S3 Access ✓
      │   └─ Mocks Locales ✓
      │
      ├─► Smoke Tests         → Invoca todas las lambdas
      │
      └─► Security Scan       → Bandit + pip-audit
              │
              ├─► Reports     → JSON consolidado
              └─► Logs        → Archivos rotados

LocalStack (AWS Emulado)
  ├─ Lambda Functions
  ├─ S3 Buckets
  ├─ CloudWatch Logs
  ├─ IAM Roles
  └─ DynamoDB (opcional)
```

---

## Estructura del repo

```
LocalStack-Lambda/
├─ docker-compose.yml
├─ Makefile
├─ README.md
├─ pyproject.toml
├─ dev-requirements.txt
│
├─ infra/terraform/
│  ├─ main.tf, variables.tf, iam.tf
│  ├─ s3.tf                       # buckets S3
│  ├─ lambdas.tf                  # todas las lambdas (dinámico)
│  └─ outputs.tf                  # lista de lambdas: lambda_names
│
├─ lambdas/
│  ├─ hello_world/
│  │  ├─ handler.py               # código de la lambda
│  │  ├─ requirements.txt         # dependencias
│  │  ├─ dist.zip                 # package generado
│  │  └─ mock_config.json         # config de mocks (auto-generado)
│  ├─ greeter/
│  ├─ getSharepointVideos/
│  └─ ...
│
├─ scripts/
│  ├─ invoke.py                   # invoca cualquier lambda
│  ├─ tail_logs.py                # tail CloudWatch (rotación y límites)
│  ├─ security_console_report.py  # reporte consolidado de seguridad
│  └─ package_all_lambdas.sh      # script de empaquetado
│
├─ testing/
│  ├─ auto_discovery.py           # auto-descubre lambdas
│  ├─ generate_mock_configs.py    # genera mock_config.json
│  ├─ mock_injector.py            # sistema de mock injection
│  ├─ auto_test_runner.py         # runner de tests automáticos
│  ├─ mock_responses/
│  │  └─ default_responses.json   # respuestas mock por defecto
│  └─ templates/
│     └─ mock_config.template.json
│
├─ reports/                       # reportes de seguridad (generados)
│  ├─ bandit_report.json
│  ├─ pip_audit_report.txt
│  └─ security_console_report.json
│
├─ logs/                          # logs de lambdas (generados)
│  ├─ hello_world.log
│  ├─ getSharepointVideos.log
│  └─ ...
│
└─ .lambdas_discovered.json       # lambdas auto-descubiertas (generado)
```

---

## Requisitos

* **Docker** + **Docker Compose** 2.0+
* **Python 3.11+**
* **make**
* **zip** (se instala con `make bootstrap`)
* **Terraform 1.9.x** (instalado o se usa la imagen oficial automáticamente)
* (Opcional) AWS CLI

> El Makefile detecta `terraform` local o usa `hashicorp/terraform:1.9.5` en Docker con `--network host`.

---

## Instalación y primer arranque

```bash
git clone <tu_repo>.git
cd LocalStack-Lambda

# Setup inicial
python3 -m venv .venv
source .venv/bin/activate
make bootstrap

# Pipeline completo (todo automático)
make all
```

El comando `make all` ejecuta automáticamente:
1. Levanta LocalStack
2. Auto-descubre lambdas
3. Genera `mock_config.json` para cada lambda
4. Empaqueta todas las lambdas
5. Despliega con Terraform
6. Ejecuta tests automáticos (6 tests por lambda)
7. Ejecuta smoke tests
8. Escanea seguridad (Bandit + pip-audit)
9. Guarda logs y reportes

---

## Comandos Make (guía rápida)

### Core

| Comando                  | Descripción                                                          |
| ------------------------ | -------------------------------------------------------------------- |
| `make help`              | Muestra todos los comandos disponibles con descripción.              |
| `make bootstrap`         | Instala herramientas de desarrollo (pip, zip, pre-commit).           |
| `make up`                | Levanta LocalStack (`docker compose up -d`).                         |
| `make down`              | Apaga LocalStack y limpia volúmenes.                                 |
| `make restart`           | Reinicia LocalStack.                                                 |
| `make status`            | Muestra estado de contenedores.                                      |
| `make clean`             | Limpia archivos generados (dist.zip, logs, reports).                 |
| `make clean-all`         | Limpieza total (incluye LocalStack data).                            |

### Discovery y Mocks

| Comando                      | Descripción                                                      |
| ---------------------------- | ---------------------------------------------------------------- |
| `make discover`              | Auto-descubre lambdas en `lambdas/`.                             |
| `make generate-mock-configs` | Genera `mock_config.json` automáticamente para cada lambda.      |

### Packaging y Deploy

| Comando             | Descripción                                                                 |
| ------------------- | --------------------------------------------------------------------------- |
| `make package-%`    | Empaqueta la lambda `%` (ej: `package-hello_world`).                        |
| `make package-all`  | Empaqueta **todas** las lambdas (auto-descubiertas).                        |
| `make plan`         | `terraform init && plan` contra LocalStack.                                 |
| `make deploy`       | `terraform init -upgrade && apply -auto-approve` (no re-empaqueta).         |
| `make nuke`         | `terraform destroy -auto-approve` (destruye infraestructura).               |
| `make list-lambdas` | Lista nombres de lambdas desde `terraform output lambda_names`.             |

### Testing

| Comando                         | Descripción                                                    |
| ------------------------------- | -------------------------------------------------------------- |
| `make test-auto`                | Tests automáticos (integración + mocks locales).               |
| `make test-unit`                | Unit tests (local, con cobertura).                             |
| `make test-integration`         | Tests de integración (LocalStack, sin cobertura).              |
| `make test-integration-verbose` | Tests de integración verbosos (prints/duraciones).             |
| `make smoke`                    | Invoca **todas** las lambdas y guarda logs en `logs/*.log`.    |

### Invocación y Logs

| Comando                                  | Descripción                                                    |
| ---------------------------------------- | -------------------------------------------------------------- |
| `make invoke-%`                          | Invoca lambda `%` con payload de ejemplo.                      |
| `make invoke FN=... PAYLOAD='{"k":"v"}'` | Invocación arbitraria.                                         |
| `make logs-%`                            | Guarda en `logs/%.log` los últimos N segundos de logs.         |
| `make logs-follow-%`                     | Tail "follow" (corta por inactividad o tiempo máximo).         |
| `make logs-quick-%`                      | Tail rápido (últimos 30 segundos).                             |

### Security

| Comando              | Descripción                                                    |
| -------------------- | -------------------------------------------------------------- |
| `make security-scan` | Ejecuta Bandit + pip-audit, genera reportes en `reports/`.    |

### Pipelines Completos

| Comando         | Descripción                                                                |
| --------------- | -------------------------------------------------------------------------- |
| `make all`      | Pipeline completo (ver descripción en [Instalación](#instalación-y-primer-arranque)). |
| `make all-down` | `make all` y luego `down`.                                                 |
| `make all-nuke` | Destruye todo (infraestructura + LocalStack + archivos).                   |
| `make dev`      | Setup rápido de desarrollo (`up` + `deploy`).                              |
| `make quick`    | Deploy + smoke tests rápido.                                               |

> **Tip**: `make help` muestra todos los comandos con formato visual mejorado.

---

## Sistema de Mocks

### Funcionamiento

El **Mock Injector** intercepta llamadas a `boto3.client()` y `requests` **sin modificar el código de las lambdas**:

Durante los tests con mocks locales:
1. El injector detecta `boto3.client('s3')`
2. Retorna un mock client con respuestas predefinidas
3. La lambda ejecuta normalmente con datos mock

---

## Testing automático

El comando `make test-auto` ejecuta **6 tests diferentes** para cada lambda:

### Suite de Tests

| Test              | Descripción                                                    |
| ----------------- | -------------------------------------------------------------- |
| **Deployment**    | Verifica que la lambda fue desplegada correctamente.           |
| **Invocación**    | Verifica que la lambda se puede invocar sin errores.           |
| **Formato**       | Verifica que la respuesta tiene formato válido (statusCode + body). |
| **Logs**          | Verifica que la lambda genera logs en CloudWatch.              |
| **S3 Access**     | Verifica acceso a S3 (solo para lambdas que usan S3).          |
| **Mocks Locales** | Ejecuta el handler localmente con mocks inyectados (si está habilitado). |

### Resultados

Los resultados se guardan en `.test_results.json`:

```json
{
  "function": "hello_world",
  "all_passed": true,
  "passed_tests": 4,
  "total_tests": 4,
  "details": [
    {"name": "Deployment", "passed": true, "details": "Lambda desplegada correctamente"},
    {"name": "Invocación", "passed": true, "details": "Lambda invocable, statusCode: 200"},
    {"name": "Formato", "passed": true, "details": "Formato válido (statusCode + body)"},
    {"name": "Logs", "passed": true, "details": "Logs generados correctamente"}
  ]
}
```

### Interpretación de Resultados

* ✓ **PASS**: Todos los tests pasaron para esa lambda
* ✗ **FAIL**: Al menos un test falló
* ⚠ **WARNING**: Test no aplicable o dependencias faltantes (no crítico)

---

## Parámetros útiles

### `RUN` - Selector de suite

Controla qué suite de tests ejecuta `run-suite`:

```bash
make all RUN=smoke   # Solo smoke tests (default)
make all RUN=tests   # Solo integration tests
make all RUN=both    # Ambas suites
```

### `SMOKE_SINCE` - Ventana de logs para smoke

Controla cuántos segundos hacia atrás buscar logs (default: 5s):

```bash
make smoke SMOKE_SINCE=3   # Menos arrastre de corridas previas
make smoke SMOKE_SINCE=10  # Más contexto de logs
```

### `LOG_WINDOW` - Ventana general de logs

Similar a `SMOKE_SINCE` pero para otros comandos:

```bash
make logs-hello_world LOG_WINDOW=30
```

> **Nota sobre logs repetidos**: Si ejecutas `make all` varias veces en menos de N segundos, verás líneas repetidas de corridas anteriores. No son dobles invocaciones, solo logs dentro de la ventana temporal. Usa ventanas pequeñas (5-10s) para minimizar esto.

---

## Cómo funciona cada pieza

### Auto-Discovery

`testing/auto_discovery.py` escanea `lambdas/` y genera `.lambdas_discovered.json`:

```json
[
  {
    "name": "hello_world",
    "path": "lambdas/hello_world",
    "has_requirements": true,
    "has_handler": true
  }
]
```

Este archivo alimenta:
* Packaging (`make package-all`)
* Deployment (Terraform itera sobre la lista)
* Testing (`make test-auto`)
* Smoke tests (`make smoke`)

### Mock Injector

`testing/mock_injector.py` usa `unittest.mock.patch` para interceptar:

```python
# Intercepta boto3.client()
with patch('boto3.client', side_effect=mock_boto3_client):
    handler({'test': True}, {})

# Intercepta requests.get/post/etc
with patch('requests.get', side_effect=mock_request):
    handler({'test': True}, {})
```

Lee configuración de `mock_config.json` y respuestas por defecto de `testing/mock_responses/default_responses.json`.

### Packaging de Lambdas

`scripts/package_all_lambdas.sh`:
* Itera sobre lambdas auto-descubiertas
* Crea entorno temporal
* Instala `requirements.txt` en `python/` layer
* Copia `handler.py` y `mock_config.json`
* Genera `dist.zip`

### Terraform

* Provider AWS v5 apuntando a `http://localhost:4566`
* Módulo dinámico en `infra/terraform/lambdas.tf` que itera sobre `.lambdas_discovered.json`
* IAM Role básico + CloudWatch Log Groups `/aws/lambda/<fn>`
* `outputs.tf` expone `lambda_names` para iteración

### Logs

`scripts/tail_logs.py` usa CloudWatch Logs API con:
* Modo "una pasada" o "follow"
* **Rotación** a `logs/<fn>.log` (max 2MB, 5 backups)
* Límites de tiempo/inactividad para evitar colgarse
* Timestamps y formateo

### Security Scanning

* **Bandit**: Análisis estático de código Python (busca vulnerabilidades comunes)
* **pip-audit**: Escanea dependencias contra base de datos de CVEs
* `scripts/security_console_report.py`: Consolida ambos reportes en JSON

---

## Security scanning

### Ejecutar Scan

```bash
make security-scan
```

### Reportes Generados

```
reports/
├─ bandit_report.json          # Reporte detallado de Bandit
├─ pip_audit_report.txt        # Output de pip-audit
└─ security_console_report.json # Consolidado con estadísticas
```

### Ver Resumen

```bash
cat reports/security_console_report.json | jq .summary
```

**Output ejemplo:**

```json
{
  "total_files": 829,
  "bandit_issues": {
    "HIGH": 9,
    "MEDIUM": 10,
    "LOW": 161,
    "TOTAL": 180
  },
  "dependency_vulnerabilities": 0
}
```

### Integración CI/CD

```yaml
# .github/workflows/ci.yml
- name: Security Scan
  run: |
    make security-scan
    # Fallar si hay issues HIGH
    if [ $(jq '.summary.bandit_issues.HIGH' reports/security_console_report.json) -gt 0 ]; then
      exit 1
    fi
```

---

## Solución de problemas

### No veo archivos en `logs/`

* Verifica que el target depende de `ensure-dirs` (el Makefile lo hace)
* Comprueba permisos de escritura
* Revisa consola: `tail_logs.py` imprime **y** guarda en archivo

### "Parece que invoca dos veces"

* Son logs de corridas anteriores dentro de la ventana temporal
* Usa `SMOKE_SINCE=3` para ventanas más cortas
* Ver [Parámetros útiles](#parámetros-útiles)

### Terraform siempre "modifica"

* Normal si `dist.zip` cambia (hash nuevo)
* Para builds deterministas: timestamps fijos, orden de archivos
* Alternativa: solo empaquetar cuando cambie código

### `terraform` no instalado

* El Makefile usa automáticamente imagen Docker oficial
* Asegura `docker` corriendo y `--network host` disponible

### Tests de integración sin cobertura

* Es esperado: la lambda corre en LocalStack (otro proceso)
* Por eso `pytest --no-cov` en integración

### Mock no funciona

```bash
# Verificar configuración
cat lambdas/mi_lambda/mock_config.json

# Regenerar configs
rm lambdas/*/mock_config.json
make generate-mock-configs
```

### Dependencias locales faltantes en tests de mocks

* Los tests de mocks locales requieren deps instaladas en tu venv
* Si faltan, el test lo marca como warning (no crítico)
* Instala deps: `pip install -r lambdas/mi_lambda/requirements.txt`

---

## Buenas prácticas y siguientes pasos

### Pirámide de Pruebas

* **Mayoría unitarias**: rápidas, sin AWS
* **Integración**: solo para contratos con AWS
* **E2E**: flujos críticos completos

### Mocks

* Deja que el sistema genere configs automáticamente
* Personaliza solo cuando sea necesario
* Usa `enabled: false` para deshabilitar

### CI/CD

* Pipeline por PR: `make all RUN=both`
* Sube `logs/*.log` y `reports/` como artifacts
* Falla build si security scan encuentra HIGH issues
* Ejecuta en contenedor Docker para reproducibilidad

### Observabilidad

* Estandariza logs JSON + `correlation_id`
* Filtra por patrón en tail (extender `tail_logs.py`)
* Agrega métricas custom (CloudWatch Metrics)

### Reutilización

* Convierte el repo en "harness" invocable desde otros repos
* Usa como template para nuevos proyectos Lambda

---

## FAQ

**¿Usa AWS real?**  
No. Todo corre en **LocalStack** (emulador local). No necesitas credenciales AWS.

**¿Puedo añadir S3/SQS/SNS/API Gateway?**  
Sí. Añade recursos Terraform. LocalStack los soporta.

**¿Puedo usar Node.js/Go/Java?**  
Sí. Replica el patrón de packaging y ajusta `runtime/handler` en Terraform.

**¿Cómo ajusto la "ventana" de logs?**  
Pasa `SMOKE_SINCE` o `LOG_WINDOW`:
```bash
make smoke SMOKE_SINCE=3  # Menos arrastre
make logs-hello_world LOG_WINDOW=30
```

**¿Los mocks son necesarios?**  
No. Si `enabled: false` en `mock_config.json`, se ejecutan tests sin mocks.

**¿Cuánto tarda el pipeline completo?**  
Aproximadamente 2-5 minutos dependiendo del número de lambdas.

**¿Funciona en CI/CD?**  
Sí. Usa `make all` en GitHub Actions, GitLab CI, Jenkins, etc.

**¿Cómo debuggeo una lambda?**  
```bash
make logs-hello_world                # Ver logs
make invoke FN=hello_world PAYLOAD='{"debug":true}'  # Invocar con payload
make logs-follow-hello_world         # Seguir logs en tiempo real
```

---