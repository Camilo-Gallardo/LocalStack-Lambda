#!/usr/bin/env python3
import os
import sys
import boto3

ENDPOINT = os.environ.get("LOCALSTACK_URL", "http://localhost:4566")
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Heurística: si alguna de estas keys está presente y con valor no vacío => probable dependencia externa
EXTERNAL_HINT_KEYS = {
    "TENANT_ID", "CLIENT_ID", "CLIENT_SECRET",
    "SITE_ID", "DRIVE_ID", "FOLDER_ID",
    "OAUTH_TOKEN_URL", "GRAPH_SCOPE",
    "GRAPH_BASE_URL", "EXTERNAL_API_BASE", "API_BASE_URL"
}

def is_testable(cfg: dict) -> bool:
    env = (cfg.get("Environment") or {}).get("Variables") or {}

    # Si se activó el shim en esa Lambda, permítela
    if env.get("ENABLE_TEST_SHIM") == "1":
        return True

    # Si hay claves "externas" con valor no vacío, márcala como NO testable
    for k in EXTERNAL_HINT_KEYS:
        v = (env.get(k) or "").strip()
        if v:
            return False

    # Si no hay indicios de externos => testable
    return True

def main():
    session = boto3.session.Session(region_name=REGION)
    client = session.client("lambda", endpoint_url=ENDPOINT)

    # lista todas las lambdas del entorno local (LocalStack)
    funcs = []
    marker = None
    while True:
        params = {}
        if marker:
            params["Marker"] = marker
        resp = client.list_functions(**params)
        funcs.extend([f["FunctionName"] for f in resp.get("Functions", [])])
        marker = resp.get("NextMarker")
        if not marker:
            break

    testables, skipped = [], []
    for name in funcs:
        cfg = client.get_function_configuration(FunctionName=name)
        if is_testable(cfg):
            testables.append(name)
        else:
            skipped.append(name)

    # Imprime las testables en stdout, una por línea (Makefile las leerá)
    print("\n".join(testables))

    # Info a stderr para que no ensucie la salida del Make
    if skipped:
        print("auto-skip => " + ", ".join(skipped), file=sys.stderr)

if __name__ == "__main__":
    main()
