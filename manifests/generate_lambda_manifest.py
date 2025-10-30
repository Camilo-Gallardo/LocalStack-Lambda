import ast
import re
from pathlib import (
    Path,
)

import yaml


def extract_lambda_info(
    handler_path: Path,
):
    """Analiza un handler.py y extrae métodos, servicios, HTTP, variables, etc."""
    info = {
        "handler": None,
        "methods": [],
        "aws_services": [],
        "external_services": [],
        "http_methods": [],
        "env_vars": [],
    }

    try:
        source = handler_path.read_text(
            encoding="utf-8"
        )
    except Exception as e:
        print(
            f"❌ Error leyendo {handler_path}: {e}"
        )
        return info

    # --- Analiza el código fuente con AST ---
    try:
        tree = ast.parse(
            source
        )
    except SyntaxError as e:
        print(
            f"⚠️ No se puede parsear {handler_path}: {e}"
        )
        return info

    # --- Métodos definidos ---
    info[
        "methods"
    ] = [
        node.name
        for node in ast.walk(
            tree
        )
        if isinstance(
            node,
            ast.FunctionDef,
        )
    ]

    # --- Detectar handler principal ---
    if (
        "handler"
        in info[
            "methods"
        ]
    ):
        info[
            "handler"
        ] = f"{handler_path.stem}.handler"

    # --- Buscar servicios AWS usados ---
    aws_matches = re.findall(
        r"boto3\.client\(['\"]([a-z0-9\-]+)['\"]\)",
        source,
    )
    info[
        "aws_services"
    ] = sorted(
        set(
            aws_matches
        )
    )

    # --- Buscar llamadas HTTP ---
    http_methods = re.findall(
        r"requests\.(get|post|put|delete|patch)\b",
        source,
    )
    info[
        "http_methods"
    ] = sorted(
        set(
            m.upper()
            for m in http_methods
        )
    )

    # --- Buscar URLs externas ---
    urls = re.findall(
        r"https?://[^\s\"')]+",
        source,
    )
    external_domains = sorted(
        set(
            re.sub(
                r"^https?://([^/]+)/?.*",
                r"\1",
                u,
            )
            for u in urls
        )
    )
    info[
        "external_services"
    ] = external_domains

    # --- Buscar variables de entorno ---
    env_pattern = re.compile(
        r"os\.(?:environ\.get|getenv)\(['\"]([A-Z0-9_]+)['\"]"
    )
    info[
        "env_vars"
    ] = sorted(
        set(
            env_pattern.findall(
                source
            )
        )
    )

    return info


def list_to_mapping(
    items,
):
    """Convierte una lista ['A', 'B'] en un diccionario {'A': None, 'B': None}."""
    return {
        item: None
        for item in items
    }


def generate_manifest_for_lambda(
    lambda_dir: Path,
):
    """Genera un test_config.yaml dentro de cada directorio lambda."""
    handler_file = (
        lambda_dir
        / "handler.js"
    )
    if (
        not handler_file.exists()
    ):
        print(
            f"⚠️ No se encontró handler.py en {lambda_dir}"
        )
        return

    print(
        f"🔍 Analizando {handler_file}..."
    )
    info = extract_lambda_info(
        handler_file
    )

    manifest = {
        "lambda_name": lambda_dir.name,
        "handler": info[
            "handler"
        ],
        "methods": list_to_mapping(
            info[
                "methods"
            ]
        ),
        "aws_services": list_to_mapping(
            info[
                "aws_services"
            ]
        ),
        "external_services": list_to_mapping(
            info[
                "external_services"
            ]
        ),
        "http_methods": list_to_mapping(
            info[
                "http_methods"
            ]
        ),
        "env_vars": list_to_mapping(
            info[
                "env_vars"
            ]
        ),
        "notes": "Agregar descripción funcional, variables opcionales y permisos IAM requeridos.",
    }

    manifest_path = (
        lambda_dir
        / "test_config.yaml"
    )

    with open(
        manifest_path,
        "w",
        encoding="utf-8",
    ) as f:
        yaml.dump(
            manifest,
            f,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    print(
        f"✅ Manifest creado: {manifest_path}"
    )


def generate_all_manifests(
    lambdas_dir: str = "lambdas",
):
    """Recorre todas las lambdas y genera sus manifests."""
    lambdas_path = Path(
        lambdas_dir
    )

    if (
        not lambdas_path.exists()
    ):
        print(
            f"❌ Carpeta {lambdas_dir} no encontrada."
        )
        return

    for subdir in (
        lambdas_path.iterdir()
    ):
        if subdir.is_dir() and not subdir.name.startswith(
            "__"
        ):
            generate_manifest_for_lambda(
                subdir
            )

    print(
        "\n📦 Todos los manifests fueron generados en sus respectivas carpetas lambda."
    )


if (
    __name__
    == "__main__"
):
    generate_all_manifests()
