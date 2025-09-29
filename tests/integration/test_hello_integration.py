import json
import os
import time
import boto3


AWS_ENDPOINT = os.getenv("AWS_ENDPOINT", "http://localhost:4566")
REGION = os.getenv("AWS_REGION", "us-east-1")


client = boto3.client(
	"lambda",
	endpoint_url=AWS_ENDPOINT,
	region_name=REGION,
	aws_access_key_id="test",
	aws_secret_access_key="test",
)


# Pequeño retry en caso de que terraform termine y la lambda demore un instante
for _ in range(10):
	try:
		client.get_function(FunctionName="hello_world")
		break
	except Exception:
		time.sleep(1)




def test_invoke_hello_world():
	payload = {"name": "Equipo QA"}
	resp = client.invoke(FunctionName="hello_world", Payload=json.dumps(payload).encode())
	assert resp["StatusCode"] == 200
	body = json.loads(resp["Payload"].read())
	assert body["ok"] is True
	assert "Hello, Equipo QA!" == body["message"]
