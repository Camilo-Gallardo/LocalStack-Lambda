import json
import os
import re
from typing import Optional, Tuple
import logging

import boto3
import requests
from botocore.exceptions import ClientError, NoCredentialsError
from unidecode import unidecode

# Set up logging for Lambda
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize S3 client
s3_client = boto3.client("s3")

# Load environment variables from environment
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
SITE_ID = os.getenv("SITE_ID")
DRIVE_ID = os.getenv("DRIVE_ID")
S3_BUCKET_NAME = os.getenv("BUCKET_NAME")
S3_FOLDER_PREFIX_JSON = os.getenv("PREFIX_JSON_FOLDER")
S3_FOLDER_PREFIX_VIDEOS = os.getenv("PREFIX_VIDEOS_FOLDER")


def normalize_filename(filename: str, extension: bool = False) -> str:
    """Normalize a filename for consistent matching."""
    name, ext = os.path.splitext(os.path.basename(filename))
    name = unidecode(name).lower()
    name = re.sub(r"-\d{8}_\d{6}-.*$", "", name)
    name = re.sub(r"[^a-z0-9-]+", "_", name).strip("_")
    return f"{name}{ext}" if extension else name


def get_access_token() -> Optional[str]:
    """Obtain an access token from Microsoft Graph."""
    url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }
    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.RequestException as e:
        logger.error(f"Error getting access token: {e}")
        return None


def process_sharepoint_file(
    access_token: str, item_id: str, s3_prefix: str
) -> Tuple[bool, Optional[str]]:
    """
    Fetches, downloads, and uploads a SharePoint file to S3.
    Returns a tuple of (success_status, original_filename).
    """
    # Get file metadata, including the download URL
    details_url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drives/{DRIVE_ID}/items/{item_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(details_url, headers=headers, timeout=10)
        response.raise_for_status()
        file_details = response.json()
        download_url = file_details.get("@microsoft.graph.downloadUrl")
        original_filename = file_details.get("name")

        if not download_url or not original_filename:
            logger.error(f"Missing download URL or filename for item {item_id}.")
            return False, None

        # Download the file content
        content_response = requests.get(download_url, timeout=30)
        content_response.raise_for_status()
        file_content = content_response.content

        # Upload the file to S3
        s3_key = f"{s3_prefix}/{normalize_filename(original_filename, extension=True)}"
        s3_client.put_object(Bucket=S3_BUCKET_NAME, Key=s3_key, Body=file_content)

        logger.info(
            f"Successfully uploaded '{original_filename}' to s3://{S3_BUCKET_NAME}/{s3_key}"
        )
        return True, original_filename

    except requests.RequestException as e:
        logger.error(f"Error processing SharePoint file for item {item_id}: {e}")
        return False, None
    except (NoCredentialsError, ClientError) as e:
        logger.error(f"Error uploading to S3 for item {item_id}: {e}")
        return False, None


def handler(event, context):
    """Lambda handler to transfer a video and its transcript from SharePoint to S3."""
    logger.info(f"Received event: {json.dumps(event)}")

    path_params = event.get("pathParameters", {})
    video_id, transcript_id = path_params.get("videoId"), path_params.get(
        "transcriptId"
    )

    if not video_id or not transcript_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing videoId or transcriptId."}),
        }

    logger.info(f"Processing video ID: {video_id} and transcript ID: {transcript_id}")

    access_token = get_access_token()
    if not access_token:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Failed to obtain access token"}),
        }
    logger.info("Successfully obtained access token")

    video_success, video_name = process_sharepoint_file(
        access_token, video_id, S3_FOLDER_PREFIX_VIDEOS
    )
    transcript_success, transcript_name = process_sharepoint_file(
        access_token, transcript_id, S3_FOLDER_PREFIX_JSON
    )

    if video_success and transcript_success:
        message = f"Successfully processed '{video_name}' and '{transcript_name}'"
        logger.info(message)
        return {
            "statusCode": 200,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"message": message}),
        }
    else:
        error_message = "One or more files failed to process."
        logger.error(error_message)
        return {
            "statusCode": 500,
            "headers": {"Access-Control-Allow-Origin": "*"},
            "body": json.dumps({"error": error_message}),
        }
