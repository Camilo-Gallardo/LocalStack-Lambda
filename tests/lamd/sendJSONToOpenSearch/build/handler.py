import os
import json
import boto3
import logging
import requests
from requests.auth import HTTPBasicAuth
from botocore.config import Config
from botocore.exceptions import BotoCoreError

# Configure logging and AWS clients
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configure Boto3 client with timeouts and retries
boto_config = Config(
    connect_timeout=10, read_timeout=30, retries={"max_attempts": 3, "mode": "adaptive"}
)
s3_client = boto3.client("s3", config=boto_config)


def get_config(event: dict) -> dict:
    """Extracts and validates configuration from the event and environment."""
    config = {
        "index": os.environ.get("INDEX"),
        "opensearch_uri": os.environ.get("OPENSEARCH_URI"),
        "opensearch_username": os.environ.get("OPENSEARCH_USERNAME"),
        "opensearch_password": os.environ.get("OPENSEARCH_PASSWORD"),
        "bucket": event["Records"][0]["s3"]["bucket"]["name"],
        "key": event["Records"][0]["s3"]["object"]["key"],
    }

    missing = [k for k, v in config.items() if not v]
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")

    if not config["key"].lower().endswith(".json"):
        raise ValueError("File is not a .json file.")

    return config


def get_s3_json(bucket: str, key: str) -> dict:
    """Downloads a file from S3 and parses it as JSON."""
    logger.info(f"Downloading s3://{bucket}/{key}")
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()
        logger.info(f"Downloaded {len(content)} bytes.")
        return json.loads(content)
    except (BotoCoreError, json.JSONDecodeError) as e:
        logger.error(f"Failed to get or parse S3 object: {e}")
        raise


def index_document(config: dict, doc_body: dict):
    """Indexes a document into OpenSearch."""
    doc_id = config["key"].replace("/", "_").replace(".json", "")
    uri = f"{config['opensearch_uri']}/{config['index']}/_doc/{doc_id}"

    logger.info(f"Indexing document {doc_id} to {uri}")

    try:
        response = requests.put(
            uri,
            json=doc_body,
            auth=HTTPBasicAuth(
                config["opensearch_username"], config["opensearch_password"]
            ),
            headers={"Content-Type": "application/json"},
            timeout=(10, 30),  # (connect, read)
        )
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)
        logger.info(f"OpenSearch response status: {response.status_code}")
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to index document in OpenSearch: {e}")
        raise


def handler(event, context):
    """Lambda handler to read a JSON file from S3 and index it into OpenSearch."""
    logger.info(f"Lambda triggered with event: {json.dumps(event)}")

    try:
        config = get_config(event)
        json_content = get_s3_json(config["bucket"], config["key"])
        opensearch_response = index_document(config, json_content)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Document indexed successfully",
                    "document_id": config["key"].replace("/", "_").replace(".json", ""),
                    "response": opensearch_response,
                }
            ),
        }
    except Exception as e:
        # Generic error handler for any failure in the process
        error_message = f"Internal server error: {str(e)}"
        logger.error(error_message, exc_info=True)
        status_code = 400 if isinstance(e, (ValueError, json.JSONDecodeError)) else 500
        return {
            "statusCode": status_code,
            "body": json.dumps({"error": error_message}),
        }
