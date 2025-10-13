#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}/.."
LAMBDAS_DIR="${REPO_ROOT}/lambdas"
PYTHON="${PYTHON:-python}"

usage(){
  cat <<-USAGE
Usage: $(basename "$0") [--skip-deps] [lambda_name ...]

Build lambdas found under the "lambdas/" directory. If no names are
provided, all immediate subdirectories of `lambdas/` are packaged.
USAGE
}

skip_deps=0
declare -a targets=()

while [[ ${#@} -gt 0 ]]; do
  case "$1" in
    --skip-deps)
      skip_deps=1; shift ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift; break ;;
    -* )
      echo "Unknown option: $1" >&2; usage; exit 2 ;;
    *)
      targets+=("$1"); shift ;;
  esac
done

if [[ ! -d "$LAMBDAS_DIR" ]]; then
  echo "No lambdas directory found at: $LAMBDAS_DIR" >&2
  exit 1
fi

if [[ ${#targets[@]} -eq 0 ]]; then
  # discover all immediate subdirectories in lambdas/
  while IFS= read -r -d $'\0' d; do
    targets+=("$(basename "$d")")
  done < <(find "$LAMBDAS_DIR" -maxdepth 1 -mindepth 1 -type d -print0)
fi

failures=()

for name in "${targets[@]}"; do
  echo "--- Packaging lambda: $name"
  lambda_dir="$LAMBDAS_DIR/$name"
  if [[ ! -d "$lambda_dir" ]]; then
    echo "  SKIP: no such directory: $lambda_dir" >&2
    failures+=("$name (missing dir)")
    continue
  fi

  pushd "$lambda_dir" >/dev/null
  rm -rf build dist.zip
  mkdir -p build/python

  if [[ $skip_deps -ne 1 && -f requirements.txt ]]; then
    echo "  Installing dependencies into build/python (using $PYTHON)"
    $PYTHON -m pip install -r requirements.txt -t build/python
  else
    if [[ -f requirements.txt ]]; then
      echo "  Skipping dependency install for $name"
    else
      echo "  No requirements.txt for $name"
    fi
  fi

  if [[ -d src ]]; then
    cp -r src/* build/ || true
  else
    echo "  Warning: no src/ directory for $name"
  fi

  echo "  Creating dist.zip"
  $PYTHON - <<'PY'
import os, zipfile
base='build'
zf=zipfile.ZipFile('dist.zip','w',compression=zipfile.ZIP_DEFLATED)
for root,dirs,files in os.walk(base):
    for f in files:
        p=os.path.join(root,f)
        zf.write(p, os.path.relpath(p, base))
zf.close()
print('  OK: dist.zip generated')
PY

  if [[ -f dist.zip ]]; then
    echo "  -> $(stat -c '%s bytes' dist.zip)"
  else
    echo "  ERROR: dist.zip not created for $name" >&2
    failures+=("$name (zip-fail)")
  fi

  popd >/dev/null
done

if [[ ${#failures[@]} -gt 0 ]]; then
  echo
  echo "lambdas sin build:" >&2
  for f in "${failures[@]}"; do
    echo " - $f" >&2
  done
  exit 1
fi

echo "dist.zip generado para: ${targets[*]}"
