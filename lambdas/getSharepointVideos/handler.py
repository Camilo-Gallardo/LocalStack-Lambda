import json
import os
from typing import Any, Dict, List

import boto3
import requests
from unidecode import unidecode

# Environment variables
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
TENANT_ID = os.environ.get("TENANT_ID")
SITE_ID = os.environ.get("SITE_ID")
DRIVE_ID = os.environ.get("DRIVE_ID")
FOLDER_ID = os.environ.get("FOLDER_ID")
BUCKET_NAME = os.environ.get("BUCKET_NAME")
PREFIX_JSON_FOLDER = os.environ.get("PREFIX_JSON_FOLDER")

s3_client = boto3.client("s3")

_TRUTHY = {"1", "true", "yes", "on"}
REQUIRED_GRAPH_ENV = [
    "CLIENT_ID",
    "CLIENT_SECRET",
    "TENANT_ID",
    "SITE_ID",
    "DRIVE_ID",
    "FOLDER_ID",
]


def should_use_mock() -> bool:
    explicit = os.environ.get("USE_MOCK_SHAREPOINT")
    if explicit is not None:
        return explicit.strip().lower() in _TRUTHY
    return any(not os.environ.get(var) for var in REQUIRED_GRAPH_ENV)


def mocked_missions() -> List[Dict[str, Any]]:
    return [
        {
            "missionId": "mock-mission-001",
            "missionName": "Mock Mission Alpha",
            "folderPath": f"{FOLDER_ID or 'mock-root'}/Mock Mission Alpha",
            "createdDate": "2024-01-01T00:00:00Z",
            "modifiedDate": "2024-01-02T00:00:00Z",
            "videoCount": 0,
            "processedCount": 0,
        }
    ]


def get_access_token() -> str:
    """Obtain Microsoft Graph API access token."""
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"

    token_data = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }

    response = requests.post(token_url, data=token_data)
    response.raise_for_status()
    return response.json()["access_token"]


def list_mission_folders(access_token: str) -> List[Dict[str, Any]]:
    """List all mission folders (immediate children of root folder)."""
    headers = {"Authorization": f"Bearer {access_token}"}

    # Get children of the root folder
    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drives/{DRIVE_ID}/items/{FOLDER_ID}/children"

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    items = response.json().get("value", [])

    # Filter only folders
    mission_folders = [item for item in items if item.get("folder") is not None]

    return mission_folders


def count_folder_items(access_token: str, folder_id: str) -> int:
    """Count items in a folder."""
    headers = {"Authorization": f"Bearer {access_token}"}

    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drives/{DRIVE_ID}/items/{folder_id}/children"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        items = response.json().get("value", [])
        # Count only files, not subfolders
        return len([item for item in items if item.get("file") is not None])
    except Exception as e:
        print(f"Error counting items in folder {folder_id}: {str(e)}")
        return 0


def get_mission_subfolders(access_token: str, mission_id: str) -> Dict[str, str]:
    """Get video and transcript subfolder IDs for a mission."""
    headers = {"Authorization": f"Bearer {access_token}"}

    url = f"https://graph.microsoft.com/v1.0/sites/{SITE_ID}/drives/{DRIVE_ID}/items/{mission_id}/children"

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        items = response.json().get("value", [])

        subfolders = {}
        for item in items:
            if item.get("folder"):
                folder_name = item.get("name", "").lower()
                if folder_name == "video":
                    subfolders["video_folder_id"] = item.get("id")
                elif folder_name == "transcript":
                    subfolders["transcript_folder_id"] = item.get("id")

        return subfolders
    except Exception as e:
        print(f"Error getting subfolders for mission {mission_id}: {str(e)}")
        return {}


def count_processed_videos(mission_name: str) -> int:
    """Count processed videos for a mission by checking S3 JSON folder."""
    try:
        # Normalize mission name for S3 path
        normalized_name = unidecode(mission_name.lower().replace(" ", "_"))
        prefix = f"{PREFIX_JSON_FOLDER}{normalized_name}/"

        response = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix=prefix,
        )

        # Count .json files
        json_files = [
            obj
            for obj in response.get("Contents", [])
            if obj["Key"].endswith(".json") and not obj["Key"].endswith(".gitkeep")
        ]

        return len(json_files)
    except Exception as e:
        print(f"Error counting processed videos for {mission_name}: {str(e)}")
        return 0


def handler(event, context):
    """Lambda handler to list all SharePoint mission folders."""
    try:
        print(f"Event: {json.dumps(event)}")

        if should_use_mock():
            print("Returning mocked SharePoint missions (offline mode enabled).")
            return {
                "statusCode": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type,Authorization",
                    "Access-Control-Allow-Methods": "GET,OPTIONS",
                },
                "body": json.dumps({"missions": mocked_missions()}),
            }

        # Get access token
        access_token = get_access_token()

        # List mission folders
        mission_folders = list_mission_folders(access_token)

        # Build response with mission metadata
        missions = []
        for folder in mission_folders:
            mission_id = folder.get("id")
            mission_name = folder.get("name")

            # Get subfolders (video and transcript)
            subfolders = get_mission_subfolders(access_token, mission_id)

            # Count videos
            video_count = 0
            if "video_folder_id" in subfolders:
                video_count = count_folder_items(access_token, subfolders["video_folder_id"])

            # Count processed videos from S3
            processed_count = count_processed_videos(mission_name)

            missions.append(
                {
                    "missionId": mission_id,
                    "missionName": mission_name,
                    "folderPath": f"{FOLDER_ID}/{mission_name}",
                    "createdDate": folder.get("createdDateTime", ""),
                    "modifiedDate": folder.get("lastModifiedDateTime", ""),
                    "videoCount": video_count,
                    "processedCount": processed_count,
                }
            )

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,OPTIONS",
            },
            "body": json.dumps({"missions": missions}),
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(
                {
                    "error": "Internal server error",
                    "message": str(e),
                }
            ),
        }
