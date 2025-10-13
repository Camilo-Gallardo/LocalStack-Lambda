import argparse
import json
import os
import boto3

def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--function", required=True)
    p.add_argument("--payload", default="{}")
    return p.parse_args()

def main():
    a = parse()
    client = boto3.client(
        "lambda",
        endpoint_url=os.environ.get("AWS_ENDPOINT","http://localhost:4566"),
        region_name=os.environ.get("REGION","us-east-1"),
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    resp = client.invoke(FunctionName=a.function, Payload=a.payload.encode())
    print(resp["StatusCode"], resp.get("FunctionError"))
    print(resp["Payload"].read().decode())

if __name__ == "__main__":
    main()
