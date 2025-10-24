#!/usr/bin/env python3
"""
Auto-descubre lambdas escaneando el directorio lambdas/
"""
from pathlib import Path
import json
import os

def discover_lambdas(base_path='lambdas'):
    """
    Escanea la carpeta lambdas/ y retorna todas las funciones encontradas
    
    Convención:
    - Cada carpeta en lambdas/ es una función
    - Debe tener handler.py
    - Opcionalmente requirements.txt
    """
    # Si estamos en testing/, subir un nivel
    if Path.cwd().name == 'testing':
        base_path = f'../{base_path}'
    
    lambdas_dir = Path(base_path)
    
    if not lambdas_dir.exists():
        print(f"❌ No se encontró el directorio {base_path}")
        return []
    
    discovered = []
    
    for item in lambdas_dir.iterdir():
        if item.is_dir():
            handler = item / 'handler.py'
            if handler.exists():
                discovered.append({
                    'name': item.name,
                    'path': str(item),
                    'handler_file': str(handler),
                    'has_requirements': (item / 'requirements.txt').exists()
                })
    
    return discovered

def main():
    lambdas = discover_lambdas()
    
    if not lambdas:
        print("❌ No se encontraron lambdas")
        return []
    
    print("🔍 Lambdas descubiertas:")
    for l in lambdas:
        reqs = "✅" if l['has_requirements'] else "⚠️"
        print(f"   {reqs} {l['name']}")
    
    print(f"\n📊 Total: {len(lambdas)} funciones lambda encontradas")
    
    # Guardar en JSON para otros scripts (en el directorio raíz)
    output_path = '.lambdas_discovered.json'
    if Path.cwd().name == 'testing':
        output_path = '../' + output_path
    
    with open(output_path, 'w') as f:
        json.dump(lambdas, f, indent=2)
    
    return lambdas

if __name__ == '__main__':
    main()