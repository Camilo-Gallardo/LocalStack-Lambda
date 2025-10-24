#!/usr/bin/env python3
"""
Genera reporte final consolidado de todo el pipeline
"""
import json
from pathlib import Path
from datetime import datetime

def load_test_results():
    """Carga resultados de tests si existen"""
    try:
        with open('.test_results.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def load_discovered_lambdas():
    """Carga lambdas descubiertas"""
    try:
        with open('.lambdas_discovered.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def generate_report():
    """Genera reporte consolidado"""
    
    print("\n" + "="*60)
    print("📊 REPORTE FINAL DEL PIPELINE")
    print("="*60)
    print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Lambdas descubiertas
    lambdas = load_discovered_lambdas()
    print(f"\n📦 Lambdas procesadas: {len(lambdas)}")
    for l in lambdas:
        print(f"   • {l['name']}")
    
    # Resultados de tests
    results = load_test_results()
    if results:
        print(f"\n🧪 Resultados de tests:")
        for result in results:
            status = "✅" if result.get('all_passed') else "❌"
            print(f"   {status} {result['function']}: {result['passed_tests']}/{result['total_tests']} tests")
    
    print("\n" + "="*60)
    print("✅ Pipeline completado exitosamente")
    print("="*60)
    print("\nPara invocar una lambda:")
    print("  make invoke FUNCTION=nombre_funcion PAYLOAD='{}'")
    print("\nPara ver logs:")
    print("  make logs")
    print()

if __name__ == '__main__':
    generate_report()