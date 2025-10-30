# Integration Contract Harness

Integration tests are driven by declarative YAML contracts stored in `tests/integration/contracts`.

## Adding a Contract

1. Create `tests/integration/contracts/<lambda_name>.yaml`.
2. Populate the contract fields:
   - `trigger_type`: one of `direct`, `apigw`, `s3`, `eventbridge`.
   - `invoke`: how the lambda should be triggered (direct payload, S3 put, API Gateway event).
   - `required_env`: environment variables to seed when running locally (values are defaults for LocalStack).
   - `localstack_resources`: buckets/objects or other LocalStack resources that must exist before invocation.
   - `http_mocks` / `model_mocks`: external dependencies handled via `responses` (HTTP) or the Bedrock stub.
   - `assertions`: expectations against lambda responses, logs, or side effects.
   - `skip_if_missing`: secrets or capabilities that should skip the contract if unavailable.
3. Validate against `tests/integration/contracts/contract.schema.json` (executed automatically by pytest).

## Running Tests

- `make test-integration` runs every contract (`pytest -m integration tests/integration`).
- `make smoke` runs only contracts tagged with the `smoke` marker.
- To execute a single contract: `pytest -m integration tests/integration -k <lambda_name>`.
- If Terraform outputs change location, update references inside the contract (`...from_output` fields).

## Fixtures Overview

- `contract_context`: resolves Terraform outputs, wires boto3 clients to LocalStack and manages setup/cleanup.
- `responses_mock`: intercepts HTTP traffic for external APIs (e.g., Microsoft Graph).
- `bedrock_stub`: stubs Bedrock runtime calls without touching lambdas.
- `event_factory`: helper functions to synthesise API Gateway and S3 event payloads.

## Capabilities and Secrets

- Declare secrets under `skip_if_missing.secrets`; the contract skips if the environment variable is not set.
- Declare optional capabilities under `skip_if_missing.capabilities`; set `CONTRACT_CAPABILITIES=cap1,cap2` to control which capabilities are active for a run.

## Tips

- Use `{tmp_prefix}` in keys to keep test data isolated and easy to clean up.
- Tag fast contracts with `markers: [smoke]` so the pipeline smoke job stays quick.
- Extend `tests/integration/test_contracts.py` with new assertion types as needed.
