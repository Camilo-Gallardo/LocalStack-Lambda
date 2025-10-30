"""
Configuration-driven integration tests for all Lambda functions.

This file automatically discovers lambdas with test_config.yaml files and:
1. Sets up environment variables
2. Creates AWS resources in LocalStack
3. Mocks HTTP calls with responses library
4. Calls the lambda handler
5. Validates response and post-execution state

Each lambda should have a test_config.yaml file in its directory.
"""

import importlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import boto3
import pytest
import responses
import yaml


class MockLambdaContext:
    """Mock AWS Lambda context for testing. Works with all lambdas."""

    def __init__(self, function_name: str = "test-function"):
        self.function_name = function_name
        self.function_version = "$LATEST"
        self.invoked_function_arn = (
            f"arn:aws:lambda:us-east-1:123456789012:function:{function_name}"
        )
        self.memory_limit_in_mb = "128"
        self.aws_request_id = f"test-{function_name}-{int(time.time())}"
        self.log_group_name = f"/aws/lambda/{function_name}"
        self.log_stream_name = f"2024/01/01/[$LATEST]test-{int(time.time())}"
        self.identity = None
        self.client_context = None

    def get_remaining_time_in_millis(self):
        """Return mock remaining execution time in milliseconds."""
        return 300000  # 5 minutes


# =======================================================================
# Lambda Discovery
# =======================================================================


def discover_lambdas() -> List[Dict[str, Any]]:
    """
    Discover all lambda functions that have a test_config.yaml file.
    Returns a list of lambda metadata dictionaries.
    """
    lambdas_dir = Path(__file__).parent.parent.parent / "lambdas"
    discovered = []

    for lambda_dir in lambdas_dir.iterdir():
        if not lambda_dir.is_dir():
            continue

        # Look for test_config.yaml or test_config.json
        config_file = lambda_dir / "test_config.yaml"
        if not config_file.exists():
            config_file = lambda_dir / "test_config.json"

        if not config_file.exists():
            continue

        # Load configuration
        try:
            with open(config_file, "r") as f:
                if config_file.suffix == ".yaml":
                    config = yaml.safe_load(f)
                else:
                    config = json.load(f)

            discovered.append(
                {
                    "name": lambda_dir.name,
                    "path": lambda_dir,
                    "config": config,
                }
            )
        except Exception as e:
            print(f"Warning: Failed to load config for {lambda_dir.name}: {e}")
            continue

    return discovered


# =======================================================================
# Configuration Template Replacement
# =======================================================================


def replace_template_vars(text: str, variables: Dict[str, Any]) -> str:
    """
    Replace {VAR_NAME} placeholders in text with actual values.
    Supports nested access like {event.pathParameters.videoId}
    """

    def get_nested_value(data: Dict, path: str) -> Any:
        keys = path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

    # Find all {placeholder} patterns
    pattern = re.compile(r"\{([^}]+)\}")

    def replacer(match):
        var_name = match.group(1)
        value = get_nested_value(variables, var_name)
        return str(value) if value is not None else match.group(0)

    return pattern.sub(replacer, text)


def interpolate_config(config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively interpolate all string values in config dict.
    Context includes: env_vars, event, etc.
    """
    if isinstance(config, dict):
        return {k: interpolate_config(v, context) for k, v in config.items()}
    elif isinstance(config, list):
        return [interpolate_config(item, context) for item in config]
    elif isinstance(config, str):
        return replace_template_vars(config, context)
    else:
        return config


# =======================================================================
# AWS Resource Setup
# =======================================================================


def setup_aws_resources(aws_config: List[Dict], endpoint_url: str):
    """
    Create AWS resources in LocalStack based on config.
    """
    for service_config in aws_config:
        service_name = service_config.get("service")
        resources = service_config.get("resources", [])

        client = boto3.client(service_name, endpoint_url=endpoint_url)

        for resource in resources:
            resource_type = resource.get("type")

            if service_name == "s3" and resource_type == "bucket":
                bucket_name = resource.get("name")
                # Retry bucket creation (LocalStack may need time)
                for attempt in range(5):
                    try:
                        client.create_bucket(Bucket=bucket_name)
                        print(f"✅ Created S3 bucket: {bucket_name}")
                        break
                    except client.exceptions.BucketAlreadyOwnedByYou:
                        print(f"ℹ️  S3 bucket already exists: {bucket_name}")
                        break
                    except Exception as e:
                        if attempt == 4:
                            raise
                        time.sleep(1)

            elif service_name == "dynamodb" and resource_type == "table":
                table_name = resource.get("name")
                key_schema = resource.get("key_schema", [])
                attribute_definitions = resource.get("attribute_definitions", [])
                billing_mode = resource.get("billing_mode", "PAY_PER_REQUEST")

                try:
                    create_params = {
                        "TableName": table_name,
                        "KeySchema": key_schema,
                        "AttributeDefinitions": attribute_definitions,
                        "BillingMode": billing_mode,
                    }

                    # Add provisioned throughput if not using PAY_PER_REQUEST
                    if billing_mode != "PAY_PER_REQUEST":
                        create_params["ProvisionedThroughput"] = {
                            "ReadCapacityUnits": resource.get("read_capacity", 5),
                            "WriteCapacityUnits": resource.get("write_capacity", 5),
                        }

                    client.create_table(**create_params)
                    print(f"✅ Created DynamoDB table: {table_name}")

                    # Wait for table to be active
                    waiter = client.get_waiter("table_exists")
                    waiter.wait(TableName=table_name)

                except client.exceptions.ResourceInUseException:
                    print(f"ℹ️  DynamoDB table already exists: {table_name}")
                except Exception as e:
                    print(f"❌ Error creating DynamoDB table {table_name}: {e}")
                    raise

            elif service_name == "sns" and resource_type == "topic":
                topic_name = resource.get("name")
                try:
                    response = client.create_topic(Name=topic_name)
                    topic_arn = response["TopicArn"]
                    print(f"✅ Created SNS topic: {topic_name} ({topic_arn})")
                except Exception as e:
                    print(f"❌ Error creating SNS topic {topic_name}: {e}")
                    raise

            # Add more resource types as needed


# =======================================================================
# HTTP Mock Setup
# =======================================================================


def setup_http_mocks(mock_configs: List[Dict], context: Dict[str, Any]):
    """
    Setup responses mocks based on config.
    """
    for mock_config in mock_configs:
        # Interpolate URL and other fields
        mock_config_interpolated = interpolate_config(mock_config, context)

        method = mock_config_interpolated.get("method", "GET").upper()
        url = mock_config_interpolated.get("url")
        response_config = mock_config_interpolated.get("response", {})

        status = response_config.get("status", 200)
        response_json = response_config.get("json")
        response_body = response_config.get("body")
        response_headers = response_config.get("headers", {})

        # Prepare body
        body_arg = None
        if response_body:
            if isinstance(response_body, str):
                body_arg = response_body.encode()
            else:
                body_arg = response_body

        # Add response mock based on method
        if method == "GET":
            responses.add(
                responses.GET,
                url,
                json=response_json if response_json else None,
                body=body_arg,
                status=status,
                headers=response_headers,
            )
        elif method == "POST":
            responses.add(
                responses.POST,
                url,
                json=response_json if response_json else None,
                body=body_arg,
                status=status,
                headers=response_headers,
            )
        elif method == "PUT":
            responses.add(
                responses.PUT,
                url,
                json=response_json if response_json else None,
                body=body_arg,
                status=status,
                headers=response_headers,
            )
        elif method == "DELETE":
            responses.add(
                responses.DELETE,
                url,
                json=response_json if response_json else None,
                body=body_arg,
                status=status,
                headers=response_headers,
            )

        print(f"🔌 Mocked {method} {url} -> {status}")


# =======================================================================
# boto3 Patching
# =======================================================================


def patched_boto3_client_factory(original_client, endpoint_url: str):
    """Return a wrapper that injects LocalStack endpoint_url."""

    def wrapper(service_name, *args, **kwargs):
        if "endpoint_url" not in kwargs:
            kwargs["endpoint_url"] = endpoint_url
        return original_client(service_name, *args, **kwargs)

    return wrapper


# =======================================================================
# Post-Execution Validation
# =======================================================================


def validate_post_execution(checks: List[Dict], endpoint_url: str):
    """
    Run post-execution checks (e.g., verify S3 objects were created).
    """
    for check in checks:
        service_name = check.get("service")
        operation = check.get("operation")
        params = check.get("params", {})
        assertions = check.get("assert", {})

        client = boto3.client(service_name, endpoint_url=endpoint_url)

        # Call the operation
        try:
            response = getattr(client, operation)(**params)
        except Exception as e:
            print(f"❌ Post-check failed: {service_name}.{operation} - {e}")
            raise

        # Validate assertions
        if "body_equals" in assertions:
            actual_body = response["Body"].read()
            expected_body = assertions["body_equals"]
            if isinstance(expected_body, str):
                expected_body = expected_body.encode()
            assert actual_body == expected_body, f"Body mismatch: {actual_body} != {expected_body}"
            print(f"✅ Post-check passed: " f"{service_name}.{operation} body matches")

        if "body_contains" in assertions:
            actual_body = response["Body"].read().decode()
            expected_substring = assertions["body_contains"]
            assert expected_substring in actual_body, f"Body doesn't contain: {expected_substring}"
            print(
                f"✅ Post-check passed: "
                f"{service_name}.{operation} contains '{expected_substring}'"
            )

        if "key_count_min" in assertions:
            key_count = response.get("KeyCount", 0)
            min_count = assertions["key_count_min"]
            assert key_count >= min_count, f"Expected at least {min_count} keys, got {key_count}"
            print(
                f"✅ Post-check passed: "
                f"{service_name}.{operation} has {key_count} keys "
                f"(min: {min_count})"
            )

        if "key_count_exact" in assertions:
            key_count = response.get("KeyCount", 0)
            exact_count = assertions["key_count_exact"]
            assert key_count == exact_count, f"Expected exactly {exact_count} keys, got {key_count}"
            print(
                f"✅ Post-check passed: " f"{service_name}.{operation} has exactly {key_count} keys"
            )


# =======================================================================
# Generic Test Function
# =======================================================================


@pytest.mark.parametrize("lambda_info", discover_lambdas(), ids=lambda lmbda: lmbda["name"])
@responses.activate
def test_lambda_config_driven(lambda_info: Dict[str, Any], monkeypatch):
    """
    Generic integration test that:
    1. Reads lambda's test_config.yaml
    2. Sets up env vars
    3. Creates AWS resources in LocalStack
    4. Mocks HTTP calls with responses
    5. Calls the lambda handler
    6. Validates response and post-execution state
    """
    lambda_name = lambda_info["name"]
    lambda_path = lambda_info["path"]
    config = lambda_info["config"]

    print(f"\n{'='*80}")
    print(f"🧪 Testing Lambda: {lambda_name}")
    print(f"{'='*80}")

    # 1. Set environment variables
    env_vars = config.get("env_vars", {})
    for key, value in env_vars.items():
        monkeypatch.setenv(key, str(value))
        print(f"🔧 Set env: {key}={value}")

    # 2. Patch boto3 to use LocalStack
    aws_endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
    original_client = boto3.client
    monkeypatch.setattr(
        boto3, "client", patched_boto3_client_factory(original_client, aws_endpoint)
    )

    # 3. Setup AWS resources
    aws_services = config.get("aws_services", [])
    if aws_services:
        setup_aws_resources(aws_services, aws_endpoint)

    # 4. Get test event and create interpolation context
    test_event = config.get("test_event", {})
    context = {
        **env_vars,
        "event": test_event,
    }

    # 5. Setup HTTP mocks
    http_mocks = config.get("http_mocks", [])
    if http_mocks:
        setup_http_mocks(http_mocks, context)

    # 6. Import and reload handler
    handler_module_path = f"lambdas.{lambda_name}.handler"
    try:
        if handler_module_path in sys.modules:
            handler_module = importlib.reload(sys.modules[handler_module_path])
        else:
            handler_module = importlib.import_module(handler_module_path)
    except ImportError:
        # Try handle.py instead of handler.py
        handler_module_path = f"lambdas.{lambda_name}.handle"
        if handler_module_path in sys.modules:
            handler_module = importlib.reload(sys.modules[handler_module_path])
        else:
            handler_module = importlib.import_module(handler_module_path)

    # 7. Call handler
    print(f"\n📤 Calling handler with event:")
    print(json.dumps(test_event, indent=2))

    # result = handler_module.handler(test_event, None)
    mock_context = MockLambdaContext(function_name=lambda_name)
    result = handler_module.handler(test_event, mock_context)

    print(f"\n📥 Handler response:")
    print(json.dumps(result, indent=2))

    # 8. Print HTTP calls made
    print(f"\n🌐 HTTP calls intercepted by responses:")
    for i, call in enumerate(responses.calls, 1):
        print(
            f"  📞 Call {i}: {call.request.method} "
            f"{call.request.url} -> {call.response.status_code}"
        )

    # 9. Validate response
    expected_response = config.get("expected_response", {})
    if expected_response:
        expected_status = expected_response.get("statusCode")
        if expected_status:
            assert result.get("statusCode") == expected_status, (
                f"Expected status {expected_status}, " f"got {result.get('statusCode')}"
            )
            print(f"✅ Status code matches: {expected_status}")

        # Check body_contains (for API Gateway format responses)
        body_contains = expected_response.get("body_contains", [])
        if body_contains:
            result_body = result.get("body", "")
            if isinstance(result_body, str):
                try:
                    result_body = json.loads(result_body) if result_body else {}
                except json.JSONDecodeError:
                    pass  # Keep as string
            result_body_str = (
                json.dumps(result_body) if isinstance(result_body, dict) else str(result_body)
            )
            for expected_text in body_contains:
                assert (
                    expected_text in result_body_str
                ), f"Expected body to contain '{expected_text}'"
                print(f"✅ Body contains: '{expected_text}'")

        # Check response_contains (for direct dict responses)
        response_contains = expected_response.get("response_contains", [])
        if response_contains:
            result_str = json.dumps(result)
            for expected_text in response_contains:
                assert (
                    expected_text in result_str
                ), f"Expected response to contain '{expected_text}'"
                print(f"✅ Response contains: '{expected_text}'")

    # 10. Post-execution checks
    post_checks = config.get("post_execution_checks", [])
    if post_checks:
        validate_post_execution(post_checks, aws_endpoint)

    print(f"\n{'='*80}")
    print(f"✅ Test passed for: {lambda_name}")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
