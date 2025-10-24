import json

def handler(event, context):
    return {
        'statusCode': 201,
        'body': json.dumps({'message': 'Greeter says hi!'})
    }