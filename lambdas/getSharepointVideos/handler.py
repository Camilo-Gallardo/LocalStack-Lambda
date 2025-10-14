import datetime
import json
import os
import re
import time
from typing import Dict, List, Optional, Set
import logging

import boto3
import requests
from botocore.exceptions import ClientError
from unidecode import unidecode

# Set up logging for Lambda
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS S3 client
s3_client = boto3.client("s3")

# Load environment variables con valores por defecto para seguridad
CLIENT_ID = os.getenv("CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "")
TENANT_ID = os.getenv("TENANT_ID", "")
SITE_ID = os.getenv("SITE_ID", "")
DRIVE_ID = os.getenv("DRIVE_ID", "")
FOLDER_ID_GENERAL = os.getenv("FOLDER_ID_GENERAL", "")
S3_BUCKET_NAME = "nuv-test-experto-nuvu-cv"
S3_FOLDER_PREFIX_JSON = os.getenv("PREFIX_JSON_FOLDER", "")
S3_FOLDER_PREFIX_JSON_VIDEOS = os.getenv("PREFIX_JSON_FOLDERVIDEOS", "")




# Definir cabeceras CORS
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,OPTIONS"
}

# Cache para guardar resultados de llamadas a la API y evitar llamadas repetidas
api_request_cache = {}
def get_access_token() -> Optional[str]:
    print("TENANT_ID", TENANT_ID)
    print("CLIENT_ID", CLIENT_ID)
    print("CLIENT_SECRET", CLIENT_SECRET)
    """Obtain an access token for Microsoft Graph API."""
    url = f"https://login.microsoftonline.com/b1aae949-a5ef-4815-b7af-f7c4aa546b28/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": "5c27b365-1057-4158-92b0-af737d1165a8",
        "client_secret": ".cf8Q~BRCXtF40s2eziQCGCQmSJ25xp2-zn2Obx~",
        "scope": "https://graph.microsoft.com/.default",
    }
    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting access token: {e}")
        return None


def make_graph_api_request(url: str, access_token: str) -> Optional[Dict]:
    """Realiza una solicitud a Microsoft Graph API con caché."""
    # Verificar que la URL sea válida
    if not url or not isinstance(url, str):
        logger.error(f"URL inválida para la solicitud a Graph API: {url}")
        return None
    
    # Verificar si hay caracteres que no deberían estar en una URL
    if '{' in url or '}' in url:
        logger.error(f"URL contiene caracteres JSON inválidos: {url}")
        # Intenta limpiar la URL si es posible
        url = re.sub(r'\{[^}]*\}', '', url)
        logger.info(f"URL limpiada: {url}")
    
    # Si la URL ya está en caché, devolver el resultado directamente
    if url in api_request_cache:
        logger.debug(f"Using cached result for {url}")
        return api_request_cache[url]
    
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        logger.debug(f"Realizando solicitud a: {url}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Guardar en caché para futuras solicitudes
        api_request_cache[url] = result
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"Error en solicitud a Graph API {url}: {e}")
        return None
    except ValueError as e:
        logger.error(f"Error al procesar respuesta JSON: {e}")
        return None




def get_first_level_folders_metadata(access_token, folder_id, site_id, drive_id):
    """Get metadata only for folders directly under FOLDER_ID_GENERAL - only name and creation date."""
    url = f"https://graph.microsoft.com/v1.0/sites/wgcp.sharepoint.com,a99fc879-51bf-44fe-bd4b-c50d618623c6,b51ed564-f2f8-468f-a388-e07184f1c0a6/drives/b!ecifqb9R_kS9S8UNYYYjxmTVHrX48o9Go4jgcYTxwKYGElwne6MiT4jJo9tfzq3i/items/01S4OGLW7U3VTA4VNR55FYZ6ZN2766YZ35/children"
    result = make_graph_api_request(url, access_token)
    folders_metadata = []

    if not result:
        logger.error("Failed to get first level folders")
        return []

    items = result.get("value", [])

    for item in items:
        if item.get("folder"):  # Solo si es una carpeta
            subfolder_id = item.get("id")
            if not subfolder_id:
                continue

            # Solo recolectar nombre y fecha de creación, sin contar videos
            folders_metadata.append({
                "id": subfolder_id,
                "name": item.get("name"),
                "createdDateTime": item.get("createdDateTime"),
                "createdBy": item.get("createdBy", {}).get("user", {}).get("displayName")
            })

    logger.info(f"Collected metadata for {len(folders_metadata)} mission folders")
    return folders_metadata

def handler(event, context):
    """
    Lambda handler to collect mission folder names and creation dates from SharePoint.
    """
    start_time = time.perf_counter()
    logger.info(f"Received event: {json.dumps(event)}")

    # Inicializar el cache de API antes de comenzar
    global api_request_cache
    api_request_cache = {}

    # Obtener token de acceso
    access_token = get_access_token()
    if not access_token:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Could not obtain access token"}),
            "headers": CORS_HEADERS
        }

    elapsed = time.perf_counter() - start_time
    logger.info(f"Successfully obtained access token in {elapsed:.4f} seconds")

    # Obtener metadatos de carpetas de primer nivel (solo nombre y fecha de creación)
    folders_metadata = get_first_level_folders_metadata(access_token, FOLDER_ID_GENERAL, SITE_ID, DRIVE_ID)

    elapsed = time.perf_counter() - start_time
    logger.info(f"Collected {len(folders_metadata)} mission folders in {elapsed:.4f} seconds")

    # Guardar los metadatos de carpetas en S3
    try:
        # Save folders metadata JSON
        metadata_key = f"{S3_FOLDER_PREFIX_JSON_VIDEOS}folders_metadata.json"
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=metadata_key,
            Body=json.dumps(folders_metadata),
            ContentType='application/json'
        )
        logger.info(f"Successfully saved folders metadata to s3://{S3_BUCKET_NAME}/{metadata_key}")

        end_time = time.perf_counter()
        total_elapsed = end_time - start_time
        logger.info(f"Total execution time: {total_elapsed:.4f} seconds")

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "message": "Mission folders collected successfully",
                "locations": {
                    "metadata": f"s3://{S3_BUCKET_NAME}/{metadata_key}"
                },
                "executionTime": f"{total_elapsed:.4f} seconds",
                "folderCount": len(folders_metadata)
            })
        }

    except ClientError as e:
        logger.error(f"Error saving to S3: {e}")
        end_time = time.perf_counter()
        total_elapsed = end_time - start_time
        logger.error(f"Total failed execution time: {total_elapsed:.4f} seconds")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "error": "Failed to save folders metadata to S3",
                "executionTime": f"{total_elapsed:.4f} seconds"
            })
        }


