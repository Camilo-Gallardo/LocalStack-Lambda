from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Optional

import boto3
import botocore
import pytest
from botocore.stub import ANY, Stubber
from jsonschema import Draft202012Validator
from responses import RequestsMock

LOCALSTACK_ENDPOINT = "http://localhost:4566"
DEFAULT_REGION = "us-east-1"
AWS_FAKE_CREDS = {
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "AWS_SESSION_TOKEN": "test",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("integration-contracts")
    group.addoption(
        "--contracts-dir",
        action="store",
        default="tests/integration/contracts",
        help="Path to directory with YAML contracts.",
    )
    group.addoption(
        "--terraform-dir",
        action="store",
        default="infra/terraform",
        help="Path containing terraform configuration.",
    )
    group.addoption(
        "--terraform-output-cache",
        action="store",
        default=".pytest-terraform-output.json",
        help="Cache file for terraform output -json.",
    )
    group.addoption(
        "--refresh-terraform-output",
        action="store_true",
        help="Force refresh of cached terraform outputs.",
    )


@pytest.fixture(scope="session", autouse=True)
def aws_credentials() -> Dict[str, str]:
    """Ensure AWS creds exist for boto3 even when running offline."""
    for key, value in AWS_FAKE_CREDS.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault("AWS_DEFAULT_REGION", DEFAULT_REGION)
    return AWS_FAKE_CREDS


@pytest.fixture(scope="session")
def boto3_session() -> boto3.session.Session:
    return boto3.session.Session(region_name=os.environ["AWS_DEFAULT_REGION"])


@pytest.fixture
def boto3_client(boto3_session: boto3.session.Session):
    """Factory fixture returning configured boto3 clients for LocalStack."""
    created = []

    def _factory(service: str, **overrides: Any):
        client = boto3_session.client(
            service,
            endpoint_url=overrides.pop("endpoint_url", LOCALSTACK_ENDPOINT),
            use_ssl=False,
            verify=False,
            config=botocore.config.Config(retries={"max_attempts": 3}),
            **overrides,
        )
        created.append(client)
        return client

    yield _factory

    for client in created:
        client.close()


@pytest.fixture(scope="session")
def terraform_outputs(pytestconfig: pytest.Config) -> Dict[str, Any]:
    """Load terraform outputs once per test session, caching the JSON when possible."""
    terraform_dir = Path(pytestconfig.getoption("--terraform-dir")).resolve()
    cache_path = Path(pytestconfig.getoption("--terraform-output-cache")).resolve()
    refresh = pytestconfig.getoption("--refresh-terraform-output")

    if cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text() or "{}")
        if cached:
            return cached
        # If cache exists but empty, force refresh
        refresh = True

    command = ["terraform", "output", "-json"]
    completed = subprocess.run(
        command,
        cwd=str(terraform_dir),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"terraform output failed (cwd={terraform_dir}):\n{completed.stderr}")
    outputs = json.loads(completed.stdout or "{}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(outputs, indent=2))
    return outputs


@pytest.fixture(scope="session")
def contract_schema(pytestconfig: pytest.Config) -> Dict[str, Any]:
    contracts_dir = Path(pytestconfig.getoption("--contracts-dir"))
    schema_path = contracts_dir / "contract.schema.json"
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def contract_validator(contract_schema: Dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(contract_schema)


@pytest.fixture(scope="session")
def contracts(pytestconfig: pytest.Config) -> Iterable[Path]:
    contracts_dir = Path(pytestconfig.getoption("--contracts-dir"))
    return sorted(contracts_dir.glob("*.yaml"))


@pytest.fixture
def responses_mock() -> Generator[RequestsMock, None, None]:
    """Yield a configured responses mock context manager."""
    with RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def bedrock_stub(boto3_session: boto3.session.Session):
    """Return a helper registering expected calls against the Bedrock runtime."""
    client = boto3_session.client(
        "bedrock-runtime",
        endpoint_url=LOCALSTACK_ENDPOINT,
        region_name=DEFAULT_REGION,
    )
    stubber = Stubber(client)
    stubber.activate()

    registered: list[str] = []
    invocations: list[Dict[str, Any]] = []
    original = client.invoke_model

    def _patched_invoke_model(**kwargs):
        invocations.append(kwargs)
        return original(**kwargs)

    client.invoke_model = _patched_invoke_model  # type: ignore[assignment]

    def _register(model_id: str, response_body: Any, status: int = 200):
        payload = (
            response_body
            if isinstance(response_body, (bytes, bytearray))
            else json.dumps(response_body)
        )
        expected = {"modelId": model_id, "body": ANY}
        if status >= 400:
            stubber.add_client_error(
                "invoke_model",
                service_error_code="BedrockInvocationError",
                http_status_code=status,
                expected_params=expected,
            )
        else:
            stubber.add_response(
                "invoke_model",
                {"body": payload, "contentType": "application/json"},
                expected_params=expected,
            )
        registered.append(model_id)

    yield {
        "client": client,
        "register": _register,
        "registered_models": registered,
        "invocations": invocations,
        "stubber": stubber,
    }

    stubber.assert_no_pending_responses()
    client.invoke_model = original  # type: ignore[assignment]
    stubber.deactivate()


@pytest.fixture
def contract_context(
    terraform_outputs: Dict[str, Any],
    boto3_client,
    responses_mock: RequestsMock,
    bedrock_stub,
):
    return ContractContext(terraform_outputs, boto3_client, responses_mock, bedrock_stub)


@dataclass
class ContractContext:
    terraform_outputs: Dict[str, Any]
    boto3_client_factory: Any
    responses: RequestsMock
    bedrock_stub: Dict[str, Any]

    def __post_init__(self) -> None:
        self.log_client = self.boto3_client_factory("logs")
        self.lambda_client = self.boto3_client_factory("lambda")
        self.s3_client = self.boto3_client_factory("s3")

    def resolve_output(self, dotted_key: str) -> Any:
        cursor = self.terraform_outputs
        for part in dotted_key.split("."):
            if part not in cursor:
                raise KeyError(f"terraform output {dotted_key} not found at {part}")
            cursor = cursor[part]
        if isinstance(cursor, dict) and "value" in cursor:
            return cursor["value"]
        return cursor

    def lambda_physical_name(self, logical_name: str) -> str:
        mapping = self.terraform_outputs.get("lambda_names", {})
        value = mapping.get("value") if isinstance(mapping, dict) else None
        if isinstance(value, dict) and logical_name in value:
            return value[logical_name]
        return logical_name

    def ensure_env(self, required_env: Dict[str, Dict[str, Any]]) -> None:
        for env_key, meta in required_env.items():
            os.environ.setdefault(env_key, str(meta.get("default", "")))

    def register_http_mocks(self, http_mocks: Iterable[Dict[str, Any]]) -> None:
        for mock in http_mocks:
            body = mock.get("body")
            if isinstance(body, dict):
                body = json.dumps(body)
            json_body = mock.get("json")
            if json_body is not None:
                body = json.dumps(json_body)
            self.responses.add(
                method=mock["method"],
                url=mock["url"],
                body=body or "",
                headers=mock.get("headers"),
                status=mock.get("status", 200),
                repeat=mock.get("repeatable", True),
            )

    def register_bedrock(self, configs: Iterable[Dict[str, Any]]) -> None:
        for cfg in configs:
            self.bedrock_stub["register"](
                model_id=cfg["model_id"],
                response_body=cfg["response_body"],
                status=cfg.get("status", 200),
            )

    def create_s3_resources(self, resources: Iterable[Dict[str, Any]], tmp_prefix: str) -> None:
        for bucket_cfg in resources:
            bucket_name = bucket_cfg.get("name")
            if not bucket_name and bucket_cfg.get("from_output"):
                bucket_name = self.resolve_output(bucket_cfg["from_output"])
            if not bucket_name:
                raise ValueError("S3 resource entry requires name or from_output")
            if bucket_cfg.get("create", True):
                try:
                    self.s3_client.create_bucket(Bucket=bucket_name)
                except self.s3_client.exceptions.BucketAlreadyOwnedByYou:
                    pass
                except self.s3_client.exceptions.BucketAlreadyExists:
                    pass
            for obj in bucket_cfg.get("objects", []):
                body = obj.get("body", "")
                if obj.get("from_file"):
                    with open(obj["from_file"], "rb") as handle:
                        body = handle.read()
                key = obj["key"].format(tmp_prefix=tmp_prefix)
                put_args = {
                    "Bucket": bucket_name,
                    "Key": key,
                    "Body": body.encode("utf-8") if isinstance(body, str) else body,
                }
                if obj.get("content_type"):
                    put_args["ContentType"] = obj["content_type"]
                self.s3_client.put_object(**put_args)

    def clear_s3_objects(self, resources: Iterable[Dict[str, Any]], tmp_prefix: str) -> None:
        for bucket_cfg in resources:
            bucket_name = bucket_cfg.get("name")
            if not bucket_name and bucket_cfg.get("from_output"):
                bucket_name = self.resolve_output(bucket_cfg["from_output"])
            if not bucket_name:
                continue
            keys = [
                obj["key"].format(tmp_prefix=tmp_prefix) for obj in bucket_cfg.get("objects", [])
            ]
            for key in keys:
                try:
                    self.s3_client.delete_object(Bucket=bucket_name, Key=key)
                except self.s3_client.exceptions.NoSuchKey:
                    continue

    def invoke_lambda(self, function_name: str, payload: Any) -> Dict[str, Any]:
        raw_payload = (
            payload
            if isinstance(payload, (bytes, bytearray))
            else json.dumps(payload).encode("utf-8")
        )
        response = self.lambda_client.invoke(
            FunctionName=function_name,
            Payload=raw_payload,
            InvocationType="RequestResponse",
        )
        payload_bytes = response["Payload"].read()
        body = payload_bytes.decode("utf-8")
        try:
            body_json = json.loads(body)
        except json.JSONDecodeError:
            body_json = body
        return {
            "status_code": response.get("StatusCode"),
            "executed_version": response.get("ExecutedVersion"),
            "payload": body_json,
            "raw_payload": payload_bytes,
        }

    def wait_for_assertion(
        self,
        func,
        timeout: int = 20,
        interval: float = 1.0,
    ) -> Any:
        deadline = time.time() + timeout
        last_exc: Optional[AssertionError] = None
        while time.time() <= deadline:
            try:
                return func()
            except AssertionError as exc:
                last_exc = exc
                time.sleep(interval)
        raise AssertionError(str(last_exc) if last_exc else "timeout waiting for assertion")
