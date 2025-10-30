"""Helpers to synthesise AWS event payloads for contract-driven integration tests."""

from __future__ import annotations

import base64
import datetime as dt
import json
import uuid
from typing import Any, Dict, Optional


def make_apigw_event(
    method: str,
    path: str,
    *,
    body: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    query: Optional[Dict[str, str]] = None,
    is_base64_encoded: bool = False,
) -> Dict[str, Any]:
    """Return an API Gateway proxy integration event payload."""
    body_str = "" if body is None else body if isinstance(body, str) else json.dumps(body)
    encoded_body = (
        base64.b64encode(body_str.encode("utf-8")).decode("utf-8")
        if is_base64_encoded
        else body_str
    )
    return {
        "resource": path,
        "path": path,
        "httpMethod": method.upper(),
        "headers": headers or {},
        "queryStringParameters": query or {},
        "pathParameters": {},
        "stageVariables": {},
        "requestContext": {
            "resourceId": "test",
            "resourcePath": path,
            "httpMethod": method.upper(),
            "requestId": str(uuid.uuid4()),
            "accountId": "000000000000",
            "stage": "local",
            "identity": {"sourceIp": "127.0.0.1"},
        },
        "body": encoded_body,
        "isBase64Encoded": is_base64_encoded,
    }


def make_s3_event(
    *,
    bucket: str,
    key: str,
    size: int = 0,
    etag: Optional[str] = None,
    event_name: str = "ObjectCreated:Put",
) -> Dict[str, Any]:
    """Return an Amazon S3 ObjectCreated event structure."""
    return {
        "Records": [
            {
                "eventVersion": "2.1",
                "eventSource": "aws:s3",
                "awsRegion": "us-east-1",
                "eventTime": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "eventName": event_name,
                "userIdentity": {"principalId": "local"},
                "requestParameters": {"sourceIPAddress": "127.0.0.1"},
                "responseElements": {
                    "x-amz-request-id": str(uuid.uuid4()),
                    "x-amz-id-2": str(uuid.uuid4()),
                },
                "s3": {
                    "s3SchemaVersion": "1.0",
                    "configurationId": "contract-test",
                    "bucket": {
                        "name": bucket,
                        "ownerIdentity": {"principalId": "local"},
                        "arn": f"arn:aws:s3:::{bucket}",
                    },
                    "object": {
                        "key": key,
                        "size": size,
                        "eTag": etag or str(uuid.uuid4()).replace("-", ""),
                        "sequencer": "001",
                    },
                },
            }
        ]
    }
