#!/usr/bin/env python3
"""
Genera automáticamente mock_config.json para lambdas que no lo tienen
"""

import json
import sys
from pathlib import Path

def analyze_lambda_for_services(lambda_path):
    """
    Analiza el código de la lambda para detectar servicios AWS usados
    """
    handler_file = Path(lambda_path) / 'handler.py'
    
    if not handler_file.exists():
        return []
    
    services_detected = []
    
    with open(handler_file) as f:
        content = f.read()
        
        # Detectar servicios boto3
        if "boto3.client('bedrock" in content or 'boto3.client("bedrock' in content:
            services_detected.append('bedrock-runtime')
        
        if "boto3.client('s3" in content or 'boto3.client("s3' in content:
            services_detected.append('s3')
        
        if "boto3.client('dynamodb" in content or 'boto3.client("dynamodb' in content:
            services_detected.append('dynamodb')
        
        if "boto3.client('sqs" in content or 'boto3.client("sqs' in content:
            services_detected.append('sqs')
        
        if "boto3.client('sns" in content or 'boto3.client("sns' in content:
            services_detected.append('sns')
        
        # Detectar llamadas externas
        has_requests = 'import requests' in content or 'from requests import' in content
        has_http_calls = 'requests.get' in content or 'requests.post' in content
        
        if has_requests and has_http_calls:
            services_detected.append('external_http')
    
    return list(set(services_detected))

def generate_mock_config(lambda_path, lambda_name):
    """
    Genera mock_config.json para una lambda
    """
    config_file = Path(lambda_path) / 'mock_config.json'
    
    # Si ya existe, no sobrescribir
    if config_file.exists():
        print(f"   ⏭️  {lambda_name}: mock_config.json ya existe (no se sobrescribe)")
        return False
    
    # Analizar servicios usados
    services = analyze_lambda_for_services(lambda_path)
    
    # Determinar si necesita mocks
    enabled = len(services) > 0
    mock_external = 'external_http' in services
    
    # Generar configuración
    config = {
        "enabled": enabled,
        "mock_external_apis": mock_external,
        "external_api_responses": {},
        "custom_boto3_responses": {},
        "_detected_services": services,
        "_auto_generated": True
    }
    
    # Si usa APIs externas, agregar placeholder
    if mock_external:
        config["external_api_responses"] = {
            "https://example.com/*": {
                "status": 200,
                "body": {
                    "message": "Mock response - Configure this in mock_config.json"
                },
                "headers": {
                    "Content-Type": "application/json"
                }
            }
        }
    
    # Guardar
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    
    status_icon = "✅" if enabled else "⏭️"
    services_str = ", ".join(services) if services else "ninguno"
    print(f"   {status_icon} {lambda_name}: generado (servicios: {services_str})")
    
    return True

def main():
    """Genera configs para todas las lambdas descubiertas"""
    
    # Leer lambdas descubiertas
    try:
        with open('.lambdas_discovered.json') as f:
            lambdas = json.load(f)
    except FileNotFoundError:
        print("❌ No se encontró .lambdas_discovered.json")
        print("   Ejecuta 'make discover' primero")
        return 1
    
    print("🤖 Generando mock_config.json automáticamente...")
    print("")
    
    generated = 0
    skipped = 0
    
    for lambda_info in lambdas:
        if generate_mock_config(lambda_info['path'], lambda_info['name']):
            generated += 1
        else:
            skipped += 1
    
    print("")
    print(f"📊 Resumen:")
    print(f"   ✅ Generados: {generated}")
    print(f"   ⏭️  Omitidos (ya existían): {skipped}")
    print(f"   📝 Total: {len(lambdas)}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
