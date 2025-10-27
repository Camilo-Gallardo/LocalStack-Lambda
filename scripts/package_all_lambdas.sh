#!/usr/bin/env bash
set -euo pipefail

PYTHON="${PYTHON:-python3}"   # use PYTHON env or default to python3
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAMBDAS="$ROOT/lambdas"

for name in $(find "$LAMBDAS" -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | sort); do
  echo "Packaging $name"
  cd "$LAMBDAS/$name"

  rm -rf build dist.zip
  mkdir -p build/python

  if [ -f requirements.txt ]; then
    "$PYTHON" -m pip install -r requirements.txt -t build/python
  fi

  if [ -d src ]; then
    cp -r src/* build/ || true
  fi

  # Ensure there is a handler module at build/handler.py
  if [ -f build/handler.py ]; then
    echo "  handler already present in build/handler.py"
  else
    if [ -f handler.py ]; then
      cp handler.py build/
      echo "  copied handler.py from lambda root"
    else
      # search for a python file that defines `handler` or `lambda_handler` in src/ first, then repo
      cand=""
      if [ -d src ]; then
        cand=$(grep -RIl -E '^[[:space:]]*def[[:space:]]+handler[[:space:]]*\(|^[[:space:]]*def[[:space:]]+lambda_handler[[:space:]]*\(' src || true)
      fi
      if [ -z "$cand" ]; then
        cand=$(grep -RIl -E '^[[:space:]]*def[[:space:]]+handler[[:space:]]*\(|^[[:space:]]*def[[:space:]]+lambda_handler[[:space:]]*\(' . || true)
      fi
      cand=$(printf "%s" "$cand" | head -n1)
      if [ -n "$cand" ]; then
        echo "  found handler in $cand; copying to build/handler.py"
        cp "$cand" build/handler.py
      else
        echo "  ERROR: no handler found for $name (checked src/ and lambda root); skipping packaging" >&2
        # cleanup to avoid creating an empty zip
        rm -rf build dist.zip
        continue
      fi
    fi
  fi

  # move installed packages to the build root so Lambda can import them
  if [ -d build/python ]; then
    # copy contents of build/python into build/ (preserve metadata)
    cp -a build/python/. build/ || true
    rm -rf build/python
  fi

  # create dist.zip (use python to avoid system zip differences)
  "$PYTHON" - <<'PY'
import os, zipfile
base='build'
zf=zipfile.ZipFile('dist.zip','w',compression=zipfile.ZIP_DEFLATED)
for root,_,files in os.walk(base):
    for f in files:
        p=os.path.join(root,f)
        zf.write(p, os.path.relpath(p, base))
zf.close()
print('OK: dist.zip generated')
PY

done