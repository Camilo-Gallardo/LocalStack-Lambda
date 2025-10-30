import io
import json
import logging
import os
import urllib.parse

import boto3
import docx2txt
from prompt_to_json import (
    PROMPT_TO_JSON,
)

# Set up logging and AWS clients
logger = (
    logging.getLogger()
)
logger.setLevel(
    logging.INFO
)
s3_client = boto3.client(
    "s3"
)
bedrock_client = boto3.client(
    "bedrock-runtime"
)

MODEL_ID = "amazon.nova-pro-v1:0"


def get_config(
    event: dict,
) -> dict:
    """Extracts and validates configuration from the event and environment."""
    bucket = event[
        "Records"
    ][
        0
    ][
        "s3"
    ][
        "bucket"
    ][
        "name"
    ]
    key = urllib.parse.unquote_plus(
        event[
            "Records"
        ][
            0
        ][
            "s3"
        ][
            "object"
        ][
            "key"
        ]
    )

    if not key.lower().endswith(
        ".docx"
    ):
        raise ValueError(
            "File is not a .docx file."
        )

    return {
        "bucket": bucket,
        "key": key,
        "output_key": key.replace(
            "transcript/",
            "json/",
        ).replace(
            ".docx",
            ".json",
        ),
        "index": os.environ.get(
            "INDEX",
            "sprintdemos",
        ),
    }


def get_s3_object_body(
    bucket: str,
    key: str,
) -> bytes:
    """Retrieves the body of an S3 object."""
    response = s3_client.get_object(
        Bucket=bucket,
        Key=key,
    )
    return response[
        "Body"
    ].read()


def extract_text_from_docx(
    file_content: bytes,
) -> str:
    """Extracts text from a .docx file's content."""
    if (
        not file_content
    ):
        raise ValueError(
            "The .docx file is empty."
        )

    text = docx2txt.process(
        io.BytesIO(
            file_content
        )
    )
    if (
        not text
        or not text.strip()
    ):
        raise ValueError(
            "No text content found in the .docx file."
        )

    logger.info(
        f"Extracted {len(text)} characters from .docx file"
    )
    return text


def invoke_bedrock_model(
    text: str,
    video_title: str,
    index: str,
) -> dict:
    """Invokes the Bedrock model to convert text to JSON."""
    formatted_prompt = PROMPT_TO_JSON.format(
        index=index,
        text=text,
        video_title=video_title,
    )

    request_body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "text": formatted_prompt
                    }
                ],
            }
        ],
        "inferenceConfig": {
            "max_new_tokens": 4000,
            "temperature": 0.1,
            "top_p": 0.9,
        },
    }

    response = bedrock_client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(
            request_body
        ),
        contentType="application/json",
    )

    response_body = json.loads(
        response[
            "body"
        ].read()
    )
    generated_text = (
        response_body.get(
            "output",
            {},
        )
        .get(
            "message",
            {},
        )
        .get(
            "content",
            [
                {}
            ],
        )[
            0
        ]
        .get(
            "text",
            "",
        )
    )

    try:
        return json.loads(
            generated_text
        )
    except (
        json.JSONDecodeError
    ) as e:
        logger.error(
            f"Generated content is not valid JSON: {e}"
        )
        return {
            "error": "Failed to parse LLM response as JSON",
            "raw_response": generated_text,
        }


def save_json_to_s3(
    bucket: str,
    key: str,
    data: dict,
):
    """Saves a dictionary as a JSON file to S3."""
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        ContentType="application/json",
    )


def handler(
    event,
    context,
):
    logger.info(
        f"Received event: {json.dumps(event)}"
    )

    config = None
    try:
        config = get_config(
            event
        )
        (
            key,
            bucket,
        ) = (
            config[
                "key"
            ],
            config[
                "bucket"
            ],
        )

        logger.info(
            f"Processing s3://{bucket}/{key}"
        )

        file_content = get_s3_object_body(
            bucket,
            key,
        )
        transcript_text = extract_text_from_docx(
            file_content
        )

        video_title = os.path.splitext(
            os.path.basename(
                key
            )
        )[
            0
        ]
        json_content = invoke_bedrock_model(
            transcript_text,
            video_title,
            config[
                "index"
            ],
        )

        save_json_to_s3(
            bucket,
            config[
                "output_key"
            ],
            json_content,
        )

        logger.info(
            f"Successfully processed and created {config['output_key']}"
        )
        return {
            "statusCode": 200,
            "body": f"Successfully processed {key} and created {config['output_key']}",
        }

    except Exception as e:
        logger.error(
            f"Error processing object: {str(e)}",
            exc_info=True,
        )
        if config:
            error_response = {
                "error": "Processing failed",
                "message": str(
                    e
                ),
                "key": config[
                    "key"
                ],
                "bucket": config[
                    "bucket"
                ],
            }
            save_json_to_s3(
                config[
                    "bucket"
                ],
                config[
                    "output_key"
                ],
                error_response,
            )

        raise e
