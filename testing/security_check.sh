#!/bin/bash
set -e

echo ""
echo "========================================"
echo "🔒 ANÁLISIS DE SEGURIDAD"
echo "========================================"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

total_issues=0

# 1. Bandit - Análisis de código
echo ""
echo "🔍 Ejecutando Bandit (vulnerabilidades en código)..."
for lambda_dir in lambdas/*/; do
    lambda_name=$(basename "$lambda_dir")
    
    if [ -f "$lambda_dir/handler.py" ]; then
        echo -n "   Analizando $lambda_name... "
        
        # Ejecutar bandit y capturar output
        if bandit -r "$lambda_dir" -f txt -q 2>&1 | grep -q "No issues identified"; then
            echo -e "${GREEN}✅ OK${NC}"
        else
            echo -e "${RED}❌ Issues encontrados${NC}"
            bandit -r "$lambda_dir" -f txt
            ((total_issues++))
        fi
    fi
done

# 2. pip-audit - Vulnerabilidades en dependencias
echo ""
echo "📦 Ejecutando pip-audit (vulnerabilidades en dependencias)..."
for lambda_dir in lambdas/*/; do
    lambda_name=$(basename "$lambda_dir")
    
    if [ -f "$lambda_dir/requirements.txt" ]; then
        echo -n "   Analizando dependencias de $lambda_name... "
        
        # Crear venv temporal y auditar
        temp_venv=$(mktemp -d)
        python3 -m venv "$temp_venv"
        source "$temp_venv/bin/activate"
        
        pip install -q -r "$lambda_dir/requirements.txt" 2>/dev/null
        
        if pip-audit --desc 2>&1 | grep -q "No known vulnerabilities"; then
            echo -e "${GREEN}✅ OK${NC}"
        else
            echo -e "${YELLOW}⚠️  Vulnerabilidades encontradas${NC}"
            pip-audit --desc
            ((total_issues++))
        fi
        
        deactivate
        rm -rf "$temp_venv"
    fi
done

# 3. Valores hardcodeados
echo ""
echo "🔎 Detectando valores hardcodeados..."
python testing/check_hardcoded.py
hardcoded_exit=$?
if [ $hardcoded_exit -ne 0 ]; then
    ((total_issues++))
fi

# Resumen
echo ""
echo "========================================"
if [ $total_issues -eq 0 ]; then
    echo -e "${GREEN}✅ SEGURIDAD: Sin problemas detectados${NC}"
    exit 0
else
    echo -e "${RED}❌ SEGURIDAD: $total_issues problema(s) detectado(s)${NC}"
    exit 1
fi