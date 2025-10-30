import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

# Configurar logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Inicializar clientes AWS
dynamodb = boto3.resource("dynamodb")
sns_client = boto3.client("sns")

# Variables de entorno
TABLE_NAME = os.getenv("DYNAMODB_TABLE")
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")


def handler(event, context):
    """
    Lambda que:
      1. Recibe datos de un usuario (por API Gateway/EventBridge).
      2. Guarda esos datos en DynamoDB.
      3. Envía una notificación a SNS.
    """

    logger.info(f"Evento recibido: {json.dumps(event)}")

    try:
        # Parsear el cuerpo del evento (JSON)
        if "body" in event:
            body = json.loads(event["body"])
        else:
            body = event  # Por si viene directo sin API Gateway

        user_id = body.get("userId")
        email = body.get("email")
        action = body.get("action", "unknown")

        if not user_id or not email:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Faltan campos obligatorios: userId o email"}),
            }

        # Insertar en DynamoDB
        table = dynamodb.Table(TABLE_NAME)
        item = {
            "UserId": user_id,
            "Email": email,
            "Action": action,
            "LambdaRequestId": context.aws_request_id,
        }

        table.put_item(Item=item)
        logger.info(f"Datos guardados en DynamoDB: {item}")

        # Enviar notificación por SNS
        message = f"Usuario {user_id} realizó la acción: {action}."
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject="Notificación de Acción de Usuario",
            Message=message,
        )

        logger.info("Notificación SNS enviada correctamente.")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {"message": "Usuario registrado y notificado correctamente", "user": item}
            ),
        }

    except ClientError as e:
        logger.error(f"Error al interactuar con AWS: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    except Exception as e:
        logger.error(f"Error inesperado: {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
