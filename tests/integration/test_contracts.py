from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml
from jsonpath_ng import parse as jsonpath_parse

from tests.integration.event_factory import make_apigw_event, make_s3_event


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "contract_path" in metafunc.fixturenames:
        contracts_dir = Path(metafunc.config.getoption("--contracts-dir"))
        contract_files = sorted(contracts_dir.glob("*.yaml"))
        params = []
        ids: list[str] = []
        for contract_path in contract_files:
            with contract_path.open("r", encoding="utf-8") as handle:
                contract = yaml.safe_load(handle) or {}
            marks = [pytest.mark.integration]
            for marker in contract.get("markers", []):
                marks.append(getattr(pytest.mark, marker))

            missing: list[str] = []
            for secret in contract.get("skip_if_missing", {}).get("secrets", []):
                if not os.environ.get(secret):
                    missing.append(f"secret {secret} not set")

            capability_clause = contract.get("skip_if_missing", {}).get("capabilities", [])
            declared_caps = {
                cap.strip().lower()
                for cap in os.environ.get("CONTRACT_CAPABILITIES", "").split(",")
                if cap.strip()
            }
            for capability in capability_clause:
                if capability.lower() not in declared_caps:
                    missing.append(f"capability {capability} not enabled")

            if missing:
                marks.append(pytest.mark.skip(reason=", ".join(missing)))

            params.append(pytest.param(contract_path, marks=marks))
            ids.append(contract_path.stem)
        metafunc.parametrize(
            "contract_path",
            params,
            ids=ids,
        )


@pytest.fixture
def contract_data(
    contract_path: Path,
    contract_validator,
    request: pytest.FixtureRequest,
) -> Dict[str, Any]:
    with contract_path.open("r", encoding="utf-8") as handle:
        contract = yaml.safe_load(handle) or {}

    contract_validator.validate(contract)

    request.node.add_marker(pytest.mark.integration)
    for marker in contract.get("markers", []):
        request.node.add_marker(getattr(pytest.mark, marker))

    return contract


def test_lambda_contract(contract_data: Dict[str, Any], contract_context) -> None:
    tmp_prefix = f"contracts/{contract_data['lambda_name']}"

    contract_context.ensure_env(contract_data.get("required_env", {}))

    http_mocks = contract_data.get("http_mocks", [])
    if http_mocks:
        contract_context.register_http_mocks(http_mocks)

    bedrock_mocks = contract_data.get("model_mocks", {}).get("bedrock")
    if bedrock_mocks:
        contract_context.register_bedrock(bedrock_mocks)

    resources = contract_data.get("localstack_resources", {}).get("s3")
    if resources:
        contract_context.create_s3_resources(resources, tmp_prefix)

    try:
        response = execute_contract(contract_data, contract_context, tmp_prefix)
        evaluate_assertions(contract_data, contract_context, response, tmp_prefix)
    finally:
        if contract_data.get("cleanup", {}).get("s3_delete_objects", True) and resources:
            contract_context.clear_s3_objects(resources, tmp_prefix)


def execute_contract(contract: Dict[str, Any], ctx, tmp_prefix: str) -> Dict[str, Any]:
    physical_lambda = ctx.lambda_physical_name(contract["lambda_name"])
    trigger = contract["trigger_type"]
    action = contract["invoke"]["action"]

    if trigger == "direct" and action == "lambda_invoke":
        payload = load_payload(contract["invoke"])
        return ctx.invoke_lambda(physical_lambda, payload)

    if trigger == "apigw":
        apigw_cfg = contract["invoke"]["apigw"]
        event = make_apigw_event(
            apigw_cfg["method"],
            apigw_cfg["path"],
            body=apigw_cfg.get("body"),
            headers=apigw_cfg.get("headers"),
            query=apigw_cfg.get("query"),
        )
        return ctx.invoke_lambda(physical_lambda, event)

    if trigger == "s3":
        if action == "s3_put_object":
            s3_cfg = contract["invoke"]["s3_object"]
            bucket = s3_cfg.get("bucket")
            if not bucket and s3_cfg.get("bucket_from_output"):
                bucket = ctx.resolve_output(s3_cfg["bucket_from_output"])
            if not bucket:
                raise ValueError("s3_put_object requires bucket or bucket_from_output")
            key = s3_cfg["key"].format(tmp_prefix=tmp_prefix)
            body = s3_cfg["body"]
            body_bytes = body.encode("utf-8") if isinstance(body, str) else body
            ctx.s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body_bytes,
                ContentType=s3_cfg.get("content_type", "application/octet-stream"),
            )
            event = make_s3_event(bucket=bucket, key=key, size=len(body_bytes))
            return ctx.invoke_lambda(physical_lambda, event)
        if action == "lambda_invoke":
            payload = load_payload(contract["invoke"])
            return ctx.invoke_lambda(physical_lambda, payload)

    if trigger == "eventbridge" and action == "eventbridge_put_event":
        # Placeholder for future extension.
        raise NotImplementedError("eventbridge trigger not yet implemented")

    raise NotImplementedError(f"Unsupported trigger/action combination: {trigger}/{action}")


def evaluate_assertions(
    contract: Dict[str, Any], ctx, response: Dict[str, Any], tmp_prefix: str
) -> None:
    for assertion in contract.get("assertions", []):
        atype = assertion["type"]

        if atype == "lambda_response_jsonpath":
            expression = jsonpath_parse(assertion["expression"])
            matches = [match.value for match in expression.find(response)]
            assert matches, f"No matches for {assertion['expression']}"
            assert (
                assertion["expected"] in matches
            ), f"Expected {assertion['expected']}, got {matches}"
            continue

        if atype == "lambda_logs_contains":
            function_name = ctx.lambda_physical_name(contract["lambda_name"])
            log_group = f"/aws/lambda/{function_name}"

            def _check_logs():
                streams = ctx.log_client.describe_log_streams(logGroupName=log_group)
                for stream in streams.get("logStreams", []):
                    events = ctx.log_client.get_log_events(
                        logGroupName=log_group,
                        logStreamName=stream["logStreamName"],
                    )
                    if any(assertion["expected"] in event["message"] for event in events["events"]):
                        return True
                raise AssertionError(f"Log message not found: {assertion['expected']}")

            ctx.wait_for_assertion(
                _check_logs,
                timeout=assertion.get("timeout_seconds", 20),
                interval=assertion.get("poll_interval_seconds", 1.0),
            )
            continue

        if atype == "s3_object_exists":
            bucket = assertion.get("bucket")
            if not bucket and assertion.get("bucket_from_output"):
                bucket = ctx.resolve_output(assertion["bucket_from_output"])
            if not bucket:
                raise AssertionError("s3_object_exists requires bucket or bucket_from_output")
            key = assertion["key"].format(tmp_prefix=tmp_prefix)

            def _check_object():
                ctx.s3_client.head_object(Bucket=bucket, Key=key)

            ctx.wait_for_assertion(
                _check_object,
                timeout=assertion.get("timeout_seconds", 20),
                interval=assertion.get("poll_interval_seconds", 1.0),
            )
            continue

        if atype == "s3_object_jsonpath":
            bucket = assertion.get("bucket")
            if not bucket and assertion.get("bucket_from_output"):
                bucket = ctx.resolve_output(assertion["bucket_from_output"])
            if not bucket:
                raise AssertionError("s3_object_jsonpath requires bucket or bucket_from_output")
            key = assertion["key"].format(tmp_prefix=tmp_prefix)

            def _check_json():
                obj = ctx.s3_client.get_object(Bucket=bucket, Key=key)
                data = json.loads(obj["Body"].read())
                matches = [
                    match.value for match in jsonpath_parse(assertion["expression"]).find(data)
                ]
                assert matches, f"No matches for {assertion['expression']}"
                assert assertion["expected"] in matches

            ctx.wait_for_assertion(
                _check_json,
                timeout=assertion.get("timeout_seconds", 30),
                interval=assertion.get("poll_interval_seconds", 1.0),
            )
            continue

        if atype == "http_call_made":
            expected_url = assertion["expected"]
            calls = [call.request.url for call in ctx.responses.calls]
            assert expected_url in calls, f"Expected HTTP call to {expected_url}, saw {calls}"
            continue

        if atype == "bedrock_invocation_count":
            expected = assertion.get("count", 1)
            actual = len(ctx.bedrock_stub["invocations"])
            assert actual == expected, f"Expected {expected} Bedrock invocations, saw {actual}"
            continue

        raise NotImplementedError(f"Unsupported assertion type: {atype}")


def load_payload(invoke_block: Dict[str, Any]) -> Any:
    if invoke_block.get("payload_file"):
        with open(invoke_block["payload_file"], "r", encoding="utf-8") as handle:
            return json.load(handle)
    return invoke_block.get("payload", {})
