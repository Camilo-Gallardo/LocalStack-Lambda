#!/usr/bin/env bash
set -euo pipefail
rm -rf build dist.zip
mkdir -p build/python
# Instala deps del runtime dentro de build/python (estructura de Lambda Layer compatible)
pip install -r requirements.txt -t build/python
# Copia el código fuente
cp -r src/* build/
# Empaqueta
cd build && zip -r ../dist.zip . >/dev/null && cd -

