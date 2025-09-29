import json, boto3, os

AWS_ENDPOINT = os.environ.get("AWS_ENDPOINT","http://localhost:4566")
REGION = os.environ.get("REGION","us-east-1")

client = boto3.client(
    "lambda",
    endpoint_url=AWS_ENDPOINT,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

resp = client.invoke(
    FunctionName="hello_world",
    Payload=json.dumps({"name": "Camilo"}).encode()
)

print(resp["StatusCode"], resp.get("FunctionError"))
print(resp["Payload"].read().decode())
