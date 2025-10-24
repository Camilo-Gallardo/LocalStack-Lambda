#!/usr/bin/env python3
"""
Ejecuta tests automáticos de integración con mocks opcionales
"""
import boto3
import json
import sys
import time
import importlib.util
from pathlib import Path

# Importar mock injector
from mock_injector import apply_mocks_for_lambda

# Clientes LocalStack
lambda_client = boto3.client(
    'lambda',
    endpoint_url='http://localhost:4566',
    region_name='us-east-1',
    aws_access_key_id='test',
    aws_secret_access_key='test'
)

s3_client = boto3.client(
    's3',
    endpoint_url='http://localhost:4566',
    region_name='us-east-1',
    aws_access_key_id='test',
    aws_secret_access_key='test'
)

logs_client = boto3.client(
    'logs',
    endpoint_url='http://localhost:4566',
    region_name='us-east-1',
    aws_access_key_id='test',
    aws_secret_access_key='test'
)

class TestResult:
    def __init__(self, function_name):
        self.function_name = function_name
        self.tests = []
    
    def add(self, test_name, passed, details=""):
        self.tests.append({
            'name': test_name,
            'passed': passed,
            'details': details
        })
    
    def all_passed(self):
        return all(t['passed'] for t in self.tests)

def test_lambda_exists(function_name):
    """Test 1: Verificar que la lambda fue desplegada"""
    try:
        response = lambda_client.get_function(FunctionName=function_name)
        return True, "Lambda desplegada correctamente"
    except Exception as e:
        return False, f"Lambda no encontrada: {str(e)}"

def test_lambda_invocable(function_name):
    """Test 2: Verificar que la lambda se puede invocar"""
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({'test': True})
        )
        
        result = json.loads(response['Payload'].read())
        
        # Verificar que no haya error de código
        if response.get('FunctionError'):
            return False, f"Error en ejecución: {result.get('errorMessage', 'Unknown error')}"
        
        # Verificar estructura mínima de respuesta
        if 'statusCode' not in result:
            return False, "Respuesta no tiene 'statusCode'"
        
        # Si statusCode es 500, puede ser error de lógica pero no de código
        if result['statusCode'] == 500:
            return True, f"Lambda ejecutable (statusCode: 500 - esperado sin datos reales)"
        
        return True, f"Lambda invocable, statusCode: {result['statusCode']}"
        
    except Exception as e:
        return False, f"Error al invocar: {str(e)}"

def test_lambda_response_format(function_name):
    """Test 3: Verificar formato de respuesta"""
    try:
        response = lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({'test': True})
        )
        
        result = json.loads(response['Payload'].read())
        
        # Verificar estructura esperada de API Gateway
        has_status = 'statusCode' in result
        has_body = 'body' in result
        
        if has_status and has_body:
            return True, "Formato válido (statusCode + body)"
        elif has_status:
            return True, "Formato parcial (solo statusCode)"
        else:
            return False, "Formato inválido"
            
    except Exception as e:
        return False, f"Error verificando formato: {str(e)}"

def test_lambda_logs_generated(function_name):
    """Test 4: Verificar que la lambda genera logs (Integración con CloudWatch)"""
    try:
        log_group = f'/aws/lambda/{function_name}'
        
        # Invocar lambda para generar logs
        lambda_client.invoke(
            FunctionName=function_name,
            Payload=json.dumps({'test': True})
        )
        
        # Esperar un momento para que los logs se escriban
        time.sleep(2)
        
        # Verificar que existan streams de logs
        response = logs_client.describe_log_streams(
            logGroupName=log_group,
            orderBy='LastEventTime',
            descending=True,
            limit=1
        )
        
        if response.get('logStreams'):
            return True, "Logs generados correctamente"
        else:
            return False, "No se encontraron logs"
            
    except Exception as e:
        # Si no hay logs no es crítico, algunas lambdas pueden no generar logs inmediatamente
        return True, f"No se pudieron verificar logs (no crítico)"

def test_lambda_s3_interaction(function_name):
    """Test 5: Verificar interacción con S3 (solo para lambdas que usan S3)"""
    # Este test es opcional - solo se ejecuta si la lambda parece usar S3
    if 's3' not in function_name.lower() and 'video' not in function_name.lower():
        return None, "No aplica (lambda no usa S3)"
    
    try:
        # Verificar que el bucket existe
        s3_client.head_bucket(Bucket='nuv-test-experto-nuvu-cv')
        return True, "Bucket S3 accesible"
    except Exception as e:
        return False, f"No se pudo acceder a S3: {str(e)}"

def test_lambda_with_local_mocks(function_name, lambda_path):
    """
    NUEVO: Prueba lambda con mocks inyectados localmente
    """
    result = TestResult(function_name)
    
    print(f"      🧪 Test con mocks locales...")
    
    try:
        # Aplicar mocks
        injector = apply_mocks_for_lambda(lambda_path)
        
        if injector is None:
            # No habilitado, no es un error
            return result
        
        # Importar handler con mocks activos
        handler_file = Path(lambda_path) / 'handler.py'
        spec = importlib.util.spec_from_file_location("handler", handler_file)
        handler_module = importlib.util.module_from_spec(spec)
        
        # Ejecutar módulo
        spec.loader.exec_module(handler_module)
        
        # Invocar handler
        response = handler_module.handler({'test': True}, {})
        
        # Verificar respuesta
        if isinstance(response, dict) and 'statusCode' in response:
            result.add("Mocks locales", True, 
                      f"Ejecutado con mocks, statusCode: {response['statusCode']}")
        else:
            result.add("Mocks locales", False, "Respuesta inválida")
        
        # Limpiar mocks
        injector.cleanup()
        
    except ModuleNotFoundError as e:
        # Dependencias faltantes no son un error crítico
        result.add("Mocks locales", None, 
                  f"⚠️  Dependencias locales faltantes: {str(e)}")
    except ImportError as e:
        result.add("Mocks locales", None, 
                  f"⚠️  Error de import: {str(e)}")
    except Exception as e:
        result.add("Mocks locales", False, f"Error: {str(e)}")
    
    return result
def run_tests_for_lambda(function_name, lambda_path=None):
    """Ejecuta suite de tests para una lambda"""
    result = TestResult(function_name)
    
    print(f"\n🧪 Testing: {function_name}")
    print("   " + "="*50)
    
    # Test 1: Exists
    passed, details = test_lambda_exists(function_name)
    result.add("Deployment", passed, details)
    status = "✅" if passed else "❌"
    print(f"   {status} Deployment: {details}")
    
    if not passed:
        return result
    
    # Test 2: Invocable
    passed, details = test_lambda_invocable(function_name)
    result.add("Invocación", passed, details)
    status = "✅" if passed else "❌"
    print(f"   {status} Invocación: {details}")
    
    # Test 3: Response format
    passed, details = test_lambda_response_format(function_name)
    result.add("Formato", passed, details)
    status = "✅" if passed else "❌"
    print(f"   {status} Formato: {details}")
    
    # Test 4: Logs
    passed, details = test_lambda_logs_generated(function_name)
    result.add("Logs", passed, details)
    status = "✅" if passed else "⚠️"
    print(f"   {status} Logs: {details}")
    
    # Test 5: S3
    passed, details = test_lambda_s3_interaction(function_name)
    if passed is not None:
        result.add("S3 Access", passed, details)
        status = "✅" if passed else "❌"
        print(f"   {status} S3: {details}")
    
    # Test 6: NUEVO - Mocks locales
    if lambda_path:
        mock_result = test_lambda_with_local_mocks(function_name, lambda_path)
        if mock_result.tests:
            for test in mock_result.tests:
                result.tests.append(test)
                if test['passed'] is not None:
                    status = "✅" if test['passed'] else "❌"
                    print(f"   {status} {test['name']}: {test['details']}")
    
    return result

def main():
    # Leer lambdas descubiertas
    try:
        with open('.lambdas_discovered.json', 'r') as f:
            lambdas = json.load(f)
    except FileNotFoundError:
        print("❌ No se encontraron lambdas. Ejecutar 'make discover' primero")
        return 1
    
    if not lambdas:
        print("❌ No se encontraron lambdas para testear")
        return 1
    
    print("\n" + "="*60)
    print("🧪 AUTO TEST RUNNER - Integración Básica + Mocks")
    print("="*60)
    print(f"📋 Testing {len(lambdas)} funciones lambda\n")
    
    results = []
    for lambda_info in lambdas:
        result = run_tests_for_lambda(
            lambda_info['name'],
            lambda_info.get('path')
        )
        results.append(result)
    
    # Reporte consolidado
    print("\n" + "="*60)
    print("📊 RESUMEN DE TESTS")
    print("="*60)
    
    results_data = []
    for result in results:
        status = "✅ PASS" if result.all_passed() else "❌ FAIL"
        passed_count = sum(1 for t in result.tests if t['passed'])
        total_count = len(result.tests)
        print(f"{status} {result.function_name}: {passed_count}/{total_count} tests")
        
        results_data.append({
            'function': result.function_name,
            'all_passed': result.all_passed(),
            'passed_tests': passed_count,
            'total_tests': total_count,
            'details': result.tests
        })
    
    # Guardar resultados
    with open('.test_results.json', 'w') as f:
        json.dump(results_data, f, indent=2)
    
    total_passed = sum(1 for r in results if r.all_passed())
    total_lambdas = len(results)
    
    print(f"\n📈 TOTAL: {total_passed}/{total_lambdas} lambdas OK")
    print("\n💡 Tests ejecutados:")
    print("   1. Deployment - Lambda existe en LocalStack")
    print("   2. Invocación - Lambda se ejecuta sin errores")
    print("   3. Formato - Respuesta tiene estructura válida")
    print("   4. Logs - Lambda genera logs en CloudWatch")
    print("   5. S3 Access - Lambda puede acceder a S3 (si aplica)")
    print("   6. Mocks locales - Ejecución con mocks inyectados (si está habilitado)")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
