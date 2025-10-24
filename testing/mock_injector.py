#!/usr/bin/env python3
"""
Mock Injector - Inyecta mocks automáticamente en boto3 y requests
Sin modificar el código de las lambdas
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from io import BytesIO

class MockInjector:
    """
    Intercepta boto3.client() y requests.request() para inyectar mocks
    """
    
    def __init__(self, mock_responses_dir='testing/mock_responses'):
        self.mock_responses_dir = Path(mock_responses_dir)
        self.default_mocks = self._load_default_mocks()
        self.active_patches = []
        self.custom_responses = {}
    
    def _load_default_mocks(self):
        """Carga respuestas mock por defecto"""
        default_file = self.mock_responses_dir / 'default_responses.json'
        try:
            with open(default_file) as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"⚠️  Warning: {default_file} not found, using empty mocks")
            return {'boto3_mocks': {}}
    
    def load_lambda_config(self, lambda_path):
        """Carga configuración específica de una lambda"""
        config_file = Path(lambda_path) / 'mock_config.json'
        if config_file.exists():
            with open(config_file) as f:
                config = json.load(f)
                # Cargar custom responses si existen
                self.custom_responses = config.get('custom_boto3_responses', {})
                return config
        return {'enabled': False}
    
    def _create_body_mock(self, body_content):
        """Crea un mock para el Body de S3/otros servicios"""
        body_mock = MagicMock()
        if isinstance(body_content, str):
            body_mock.read.return_value = body_content.encode('utf-8')
        else:
            body_mock.read.return_value = json.dumps(body_content).encode('utf-8')
        return body_mock
    
    def _create_mock_client(self, service_name):
        """Crea un cliente boto3 mockeado"""
        mock_client = MagicMock()
        
        # Prioridad: custom responses > default responses
        service_mocks = {}
        
        # 1. Cargar defaults
        default_service = self.default_mocks.get('boto3_mocks', {}).get(service_name, {})
        service_mocks.update(default_service)
        
        # 2. Sobrescribir con customs
        if service_name in self.custom_responses:
            service_mocks.update(self.custom_responses[service_name])
        
        # Configurar cada método
        for method_name, config in service_mocks.items():
            response = config.get('response', {}).copy()
            
            # Caso especial: Body como stream
            if 'Body' in response:
                response['Body'] = self._create_body_mock(response['Body'])
            
            # Configurar método
            method_mock = getattr(mock_client, method_name)
            method_mock.return_value = response
        
        return mock_client
    
    def patch_boto3(self):
        """Patchea boto3.client() globalmente"""
        
        def mock_boto3_client(service_name, **kwargs):
            """Interceptor de boto3.client()"""
            print(f"      🔧 Mock: boto3.client('{service_name}')")
            return self._create_mock_client(service_name)
        
        patcher = patch('boto3.client', side_effect=mock_boto3_client)
        self.active_patches.append(patcher)
        patcher.start()
        
        return self
    
    def patch_requests(self, external_api_config):
        """Patchea requests para APIs externas"""
        if not external_api_config:
            return self
        
        def mock_request_method(method_name):
            """Crea un mock para un método HTTP específico"""
            def mock_func(url, **kwargs):
                print(f"      🌐 Mock: {method_name.upper()} {url}")
                
                # Buscar mock para esta URL
                for url_pattern, response_config in external_api_config.items():
                    pattern = url_pattern.replace('*', '')
                    if pattern in url:
                        mock_response = MagicMock()
                        mock_response.status_code = response_config.get('status', 200)
                        mock_response.json.return_value = response_config.get('body', {})
                        mock_response.text = json.dumps(response_config.get('body', {}))
                        mock_response.content = mock_response.text.encode('utf-8')
                        mock_response.headers = response_config.get('headers', {})
                        mock_response.ok = 200 <= mock_response.status_code < 300
                        return mock_response
                
                # Si no hay mock, retornar 404 en lugar de error
                print(f"      ⚠️  No mock configured for {method_name.upper()} {url}, returning 404")
                mock_response = MagicMock()
                mock_response.status_code = 404
                mock_response.json.return_value = {"error": "Not mocked"}
                mock_response.text = '{"error": "Not mocked"}'
                mock_response.ok = False
                return mock_response
            
            return mock_func
        
        # Patchear todos los métodos HTTP
        for method in ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']:
            patcher = patch(f'requests.{method}', side_effect=mock_request_method(method))
            self.active_patches.append(patcher)
            patcher.start()
        
        return self
    
    def cleanup(self):
        """Limpia todos los patches"""
        for patcher in self.active_patches:
            patcher.stop()
        self.active_patches = []
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


def apply_mocks_for_lambda(lambda_path):
    """
    Aplica mocks para una lambda específica
    Retorna el injector configurado o None si no está habilitado
    """
    injector = MockInjector()
    
    # Cargar config de la lambda
    lambda_config = injector.load_lambda_config(lambda_path)
    
    # Si no está habilitado, retornar None
    if not lambda_config.get('enabled', False):
        return None
    
    # Patchear boto3
    injector.patch_boto3()
    
    # Patchear requests si está configurado
    if lambda_config.get('mock_external_apis', False):
        external_apis = lambda_config.get('external_api_responses', {})
        injector.patch_requests(external_apis)
    
    return injector
