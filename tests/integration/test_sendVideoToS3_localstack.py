import importlib
import json
import os
import time

import boto3
import responses


def _patched_boto3_client_factory(original_client, endpoint_url_env="AWS_ENDPOINT_URL"):
    """Return a wrapper that injects endpoint_url from env for services that support it."""

    def wrapper(service_name, *args, **kwargs):
        endpoint = os.environ.get(endpoint_url_env)
        # if user already passed endpoint_url, keep it
        if "endpoint_url" not in kwargs and endpoint:
            kwargs["endpoint_url"] = endpoint
        return original_client(service_name, *args, **kwargs)

    return wrapper


@responses.activate
def test_send_video_to_s3_localstack(monkeypatch):
    """
    Integration test for sendVideoToS3 lambda:
    - Uses LocalStack for S3
    - Uses responses to mock Microsoft Graph API calls
    """
    # Require LocalStack running on localhost:4566
    aws_endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")

    # Set env vars needed by the lambda
    monkeypatch.setenv("CLIENT_ID", "test-client-id")
    monkeypatch.setenv("CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("TENANT_ID", "test-tenant-id")
    monkeypatch.setenv("SITE_ID", "test-site-id")
    monkeypatch.setenv("DRIVE_ID", "test-drive-id")
    monkeypatch.setenv("BUCKET_NAME", "test-video-bucket")
    monkeypatch.setenv("PREFIX_JSON_FOLDER", "transcripts")
    monkeypatch.setenv("PREFIX_VIDEOS_FOLDER", "videos")

    # Ensure boto3 uses LocalStack endpoint by patching boto3.client before import
    original_client = boto3.client
    monkeypatch.setattr(boto3, "client", _patched_boto3_client_factory(original_client))

    # Now import the handler module so its module-level clients get created with LocalStack endpoint
    import lambdas.sendVideoToS3.handler as handler_module

    importlib.reload(handler_module)

    # Create bucket in LocalStack
    s3 = boto3.client("s3", endpoint_url=aws_endpoint)
    # localstack may need a moment; try a few times
    for _ in range(5):
        try:
            s3.create_bucket(Bucket="test-video-bucket")
            break
        except Exception:
            time.sleep(1)

    # Mock Microsoft Graph API calls
    # 1. Token endpoint
    token_url = "https://login.microsoftonline.com/test-tenant-id/oauth2/v2.0/token"
    responses.add(responses.POST, token_url, json={"access_token": "fake-access-token"}, status=200)

    # 2. Video file metadata endpoint
    video_id = "video-item-123"
    video_details_url = (
        f"https://graph.microsoft.com/v1.0/sites/test-site-id/drives/test-drive-id/items/{video_id}"
    )
    video_download_url = "https://fake-download-url.com/video.mp4"
    responses.add(
        responses.GET,
        video_details_url,
        json={"@microsoft.graph.downloadUrl": video_download_url, "name": "sample-video.mp4"},
        status=200,
    )

    # 3. Video download endpoint
    responses.add(responses.GET, video_download_url, body=b"fake-video-content", status=200)

    # 4. Transcript file metadata endpoint
    transcript_id = "transcript-item-456"
    transcript_details_url = f"https://graph.microsoft.com/v1.0/sites/test-site-id/drives/test-drive-id/items/{transcript_id}"
    transcript_download_url = "https://fake-download-url.com/transcript.vtt"
    responses.add(
        responses.GET,
        transcript_details_url,
        json={
            "@microsoft.graph.downloadUrl": transcript_download_url,
            "name": "sample-transcript.vtt",
        },
        status=200,
    )

    # 5. Transcript download endpoint
    responses.add(
        responses.GET, transcript_download_url, body=b"fake-transcript-content", status=200
    )

    # Prepare the event as API Gateway would send it
    event = {"pathParameters": {"videoId": video_id, "transcriptId": transcript_id}}

    # Call the handler
    print("\n" + "=" * 80)
    print("📤 CALLING HANDLER WITH EVENT:")
    print(json.dumps(event, indent=2))
    print("=" * 80)

    result = handler_module.handler(event, None)

    print("\n" + "=" * 80)
    print("📥 HANDLER RESULT:")
    print(json.dumps(result, indent=2))
    print("=" * 80)

    print("\n" + "=" * 80)
    print("🌐 HTTP CALLS MADE BY RESPONSES:")
    print(f"Total calls: {len(responses.calls)}")
    for i, call in enumerate(responses.calls, 1):
        print(f"\n  📞 Call {i}:")
        print(f"     Method: {call.request.method}")
        print(f"     URL: {call.request.url}")
        print(f"     Headers: {dict(call.request.headers)}")
        if call.request.body:
            body_preview = str(call.request.body)[:200]
            print(f"     Request Body: {body_preview}...")
        print(f"     Response Status: {call.response.status_code}")
        response_preview = (
            call.response.text[:200]
            if hasattr(call.response, "text")
            else str(call.response.content[:200])
        )
        print(f"     Response Body: {response_preview}...")
    print("=" * 80 + "\n")

    # Assertions
    assert result.get("statusCode") == 200
    body = json.loads(result.get("body") or "{}")
    assert "message" in body
    assert "sample-video.mp4" in body["message"]
    assert "sample-transcript.vtt" in body["message"]

    # Verify files were uploaded to S3
    # Note: The handler uses PREFIX_VIDEOS_FOLDER which has trailing slash,
    # creating paths like "videos//filename"
    video_key = "videos/sample-video.mp4"  # normalize_filename keeps hyphens
    transcript_key = "transcripts/sample-transcript.vtt"

    video_obj = s3.get_object(Bucket="test-video-bucket", Key=video_key)
    assert video_obj["Body"].read() == b"fake-video-content"

    transcript_obj = s3.get_object(Bucket="test-video-bucket", Key=transcript_key)
    assert transcript_obj["Body"].read() == b"fake-transcript-content"


@responses.activate
def test_send_video_to_s3_missing_params(monkeypatch):
    """Test that the lambda returns 400 when pathParameters are missing."""
    aws_endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")

    # Set env vars
    monkeypatch.setenv("CLIENT_ID", "test-client-id")
    monkeypatch.setenv("CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("TENANT_ID", "test-tenant-id")
    monkeypatch.setenv("SITE_ID", "test-site-id")
    monkeypatch.setenv("DRIVE_ID", "test-drive-id")
    monkeypatch.setenv("BUCKET_NAME", "test-video-bucket")
    monkeypatch.setenv("PREFIX_JSON_FOLDER", "transcripts/")
    monkeypatch.setenv("PREFIX_VIDEOS_FOLDER", "videos/")

    # Patch boto3.client
    original_client = boto3.client
    monkeypatch.setattr(boto3, "client", _patched_boto3_client_factory(original_client))

    # Import handler
    import lambdas.sendVideoToS3.handler as handler_module

    importlib.reload(handler_module)

    # Event with missing videoId
    event = {"pathParameters": {"transcriptId": "transcript-123"}}

    result = handler_module.handler(event, None)

    assert result.get("statusCode") == 400
    body = json.loads(result.get("body") or "{}")
    assert "error" in body
    assert "Missing" in body["error"]


@responses.activate
def test_send_video_to_s3_token_failure(monkeypatch):
    """Test that the lambda returns 500 when token acquisition fails."""
    aws_endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")

    # Set env vars
    monkeypatch.setenv("CLIENT_ID", "test-client-id")
    monkeypatch.setenv("CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("TENANT_ID", "test-tenant-id")
    monkeypatch.setenv("SITE_ID", "test-site-id")
    monkeypatch.setenv("DRIVE_ID", "test-drive-id")
    monkeypatch.setenv("BUCKET_NAME", "test-video-bucket")
    monkeypatch.setenv("PREFIX_JSON_FOLDER", "transcripts/")
    monkeypatch.setenv("PREFIX_VIDEOS_FOLDER", "videos/")

    # Patch boto3.client
    original_client = boto3.client
    monkeypatch.setattr(boto3, "client", _patched_boto3_client_factory(original_client))

    # Import handler
    import lambdas.sendVideoToS3.handler as handler_module

    importlib.reload(handler_module)

    # Mock token endpoint to fail
    token_url = "https://login.microsoftonline.com/test-tenant-id/oauth2/v2.0/token"
    responses.add(responses.POST, token_url, json={"error": "invalid_client"}, status=401)

    event = {"pathParameters": {"videoId": "video-123", "transcriptId": "transcript-456"}}

    result = handler_module.handler(event, None)

    assert result.get("statusCode") == 500
    body = json.loads(result.get("body") or "{}")
    assert "error" in body
    assert "access token" in body["error"].lower()
