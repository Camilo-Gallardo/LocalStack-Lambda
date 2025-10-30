import json
import os
import re
from typing import Dict, List, Optional, Set
import logging

import boto3
import requests
from botocore.exceptions import ClientError
try:
    from unidecode import unidecode  # type: ignore
except ImportError:  # pragma: no cover - fallback for local/offline packaging
    logger = logging.getLogger(__name__)
    logger.warning("unidecode module not available; falling back to no-op normalization")

    def unidecode(value: str) -> str:  # type: ignore
        return value

# Set up logging for Lambda
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS S3 client
s3_client = boto3.client("s3")

# Load environment variables
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
SITE_ID = os.getenv("SITE_ID")
DRIVE_ID = os.getenv("DRIVE_ID")
FOLDER_ID = os.getenv("FOLDER_ID")
S3_BUCKET_NAME = os.getenv("BUCKET_NAME")
S3_FOLDER_PREFIX_JSON = os.getenv("PREFIX_JSON_FOLDER")


def normalize_filename(filename: str, extension: bool = False) -> str:
    """Normalize a filename for consistent matching."""
    name, ext = os.path.splitext(os.path.basename(filename))
    name = unidecode(name).lower()
    name = re.sub(r"-\d{8}_\d{6}-.*$", "", name)
    name = re.sub(r"[^a-z0-9-]+", "_", name).strip("_")
    return f"{name}{ext}" if extension else name


def get_access_token() -> Optional[str]:
    """Obtain an access token for Microsoft Graph API."""
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


def list_sharepoint_files(access_token: str, folder_id: str) -> Optional[List[Dict]]:
    """List files in a specific SharePoint folder."""
    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drives/{DRIVE_ID}/items/{folder_id}/children"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json().get("value", [])
    except requests.RequestException as e:
        logger.error(f"Error listing SharePoint files for folder {folder_id}: {e}")
        return None


def get_processed_s3_filenames() -> Set[str]:
    """List and normalize filenames from S3 for quick lookups."""
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=S3_FOLDER_PREFIX_JSON)
        return {
            normalize_filename(item["Key"])
            for page in pages
            for item in page.get("Contents", [])
        }
    except ClientError as e:
        logger.error(f"Error listing S3 files: {e}")
        return set()


def get_mission_folders(access_token: str) -> Optional[List[Dict]]:
    """List all mission folders within the main FOLDER_ID."""
    mission_folders = list_sharepoint_files(access_token, FOLDER_ID)
    if mission_folders is None:
        return None

    # Filter only folders (not files)
    return [item for item in mission_folders if item.get("folder")]


def get_subfolder_by_name(
    access_token: str, parent_folder_id: str, subfolder_name: str
) -> Optional[str]:
    """Find a specific subfolder by name within a parent folder."""
    items = list_sharepoint_files(access_token, parent_folder_id)
    if items is None:
        return None

    for item in items:
        if (
            item.get("folder")
            and item.get("name", "").lower() == subfolder_name.lower()
        ):
            return item.get("id")
    return None


def handler(event, context):
    """
    Lambda handler to list video files from SharePoint missions, check their processing status against S3,
    and return a list of missions with their videos and corresponding transcript.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    access_token = get_access_token()
    if not access_token:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Could not obtain access token"}),
        }
    logger.info("Successfully obtained access token")

    # Get all mission folders
    mission_folders = get_mission_folders(access_token)
    if mission_folders is None:
        return {
            "statusCode": 500,
            "body": json.dumps(
                {"error": "Failed to retrieve mission folders from SharePoint"}
            ),
        }

    logger.info(f"Found {len(mission_folders)} mission folders")

    processed_files_set = get_processed_s3_filenames()
    logger.info(f"Found {len(processed_files_set)} processed files in S3")

    missions_list = []

    for mission_folder in mission_folders:
        mission_id = mission_folder.get("id")
        mission_name = mission_folder.get("name", "")

        logger.info(f"Processing mission: {mission_name}")

        # Find video and transcript subfolders within this mission
        video_folder_id = get_subfolder_by_name(access_token, mission_id, "video")
        transcript_folder_id = get_subfolder_by_name(
            access_token, mission_id, "transcript"
        )

        if not video_folder_id:
            logger.warning(f"No 'video' folder found in mission: {mission_name}")
            continue

        if not transcript_folder_id:
            logger.warning(f"No 'transcript' folder found in mission: {mission_name}")

        # Get files from video folder
        video_files = list_sharepoint_files(access_token, video_folder_id)
        if video_files is None:
            logger.error(f"Failed to retrieve video files for mission: {mission_name}")
            continue

        # Get files from transcript folder (if it exists)
        transcript_files = []
        if transcript_folder_id:
            transcript_files = list_sharepoint_files(access_token, transcript_folder_id)
            if transcript_files is None:
                logger.warning(
                    f"Failed to retrieve transcript files for mission: {mission_name}"
                )
                transcript_files = []

        logger.info(
            f"Mission {mission_name}: {len(video_files)} videos, {len(transcript_files)} transcripts"
        )

        # Create lookup for transcript by normalized name
        transcript_by_name = {
            normalize_filename(f.get("name", "")): f for f in transcript_files
        }

        # Process videos for this mission
        mission_videos = []
        for video in video_files:
            video_name_normalized = normalize_filename(video.get("name", ""))
            matching_transcript = transcript_by_name.get(video_name_normalized)

            mission_videos.append(
                {
                    "videoId": video.get("id"),
                    "transcriptId": (
                        matching_transcript.get("id") if matching_transcript else None
                    ),
                    "title": video.get("name"),
                    "processed": video_name_normalized in processed_files_set,
                    "webUrl": video.get("webUrl"),
                    "missionId": mission_id,
                    "missionName": mission_name,
                }
            )

        # Add mission to the list if it has videos
        if mission_videos:
            missions_list.append(
                {
                    "missionId": mission_id,
                    "missionName": mission_name,
                    "videos": mission_videos,
                    "videoCount": len(mission_videos),
                    "processedCount": sum(1 for v in mission_videos if v["processed"]),
                }
            )

    total_videos = sum(mission["videoCount"] for mission in missions_list)
    logger.info(
        f"Returning {len(missions_list)} missions with {total_videos} total videos"
    )

    return {
        "statusCode": 200,
        "headers": {
            "Access-Control-Allow-Origin": "*",  # Consider making this more restrictive
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(missions_list),
    }
