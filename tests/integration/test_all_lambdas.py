# tests/integration/test_all_lambdas.py
import json, os, time, subprocess, json as pyjson
import boto3, pytest

AWS_ENDPOINT = os.getenv("AWS_ENDPOINT","http://localhost:4566")
REGION = os.getenv("REGION","us-east-1")

def _tf_lambda_names():
    try:
        out = subprocess.check_output(
            ["bash","-lc","cd infra/terraform && terraform output -json lambda_names"],
            stderr=subprocess.STDOUT,
            text=True
        )
        return pyjson.loads(out)
    except Exception:
        # fallback: nombres por carpetas que tengan dist.zip
        base = "lambdas"
        names = []
        for name in os.listdir(base):
            if os.path.isfile(os.path.join(base, name, "dist.zip")):
                names.append(name)
        return names

FN_NAMES = _tf_lambda_names()

client = boto3.client(
    "lambda",
    endpoint_url=AWS_ENDPOINT,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

@pytest.mark.parametrize("fn", FN_NAMES)
def test_invoke(fn):
    for _ in range(10):
        try:
            client.get_function(FunctionName=fn); break
        except Exception:
            time.sleep(1)
    resp = client.invoke(FunctionName=fn, Payload=json.dumps({"name":"Equipo QA"}).encode())
    assert resp["StatusCode"] == 200
    body = json.loads(resp["Payload"].read())
    assert body.get("ok") is True
    assert isinstance(body.get("message",""), str)
