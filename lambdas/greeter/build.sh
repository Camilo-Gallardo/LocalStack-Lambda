#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

rm -rf build dist.zip
mkdir -p build/python

# Usa el Python activo (de tu venv) y no 'pip' a secas
python -m pip install -r requirements.txt -t build/python

# Copia el código
cp -r src/* build/

# Empaquetado en Python (evita binario 'zip' del sistema)
python - <<'PY'
import os, zipfile
base="build"
zf=zipfile.ZipFile("dist.zip","w",compression=zipfile.ZIP_DEFLATED)
for root,_,files in os.walk(base):
    for f in files:
        p=os.path.join(root,f)
        zf.write(p, os.path.relpath(p, base))
zf.close()
print("OK: dist.zip generado")
PY
