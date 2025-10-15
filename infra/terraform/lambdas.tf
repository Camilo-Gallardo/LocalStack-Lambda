# Busca todos los dist.zip: lambdas/<nombre>/dist.zip
locals {
  lambda_zip_paths = fileset("${path.module}/../../lambdas", "*/dist.zip")

  lambdas = {
    for rel in local.lambda_zip_paths :
    split("/", rel)[0] => {
      zip     = "${path.module}/../../lambdas/${rel}"
      handler = "handler.handler"
      runtime = "python3.11"
    }
  }

  # Env común para todas (si quieres algo global)
  common_env = {
    STAGE = "local"
  }
}
# Log groups por función
resource "aws_cloudwatch_log_group" "lg" {
  for_each          = local.lambdas
  name              = "/aws/lambda/${each.key}"
  retention_in_days = 7
}
resource "aws_lambda_function" "fn" {
  for_each         = local.lambdas
  function_name    = each.key
  role             = aws_iam_role.lambda_exec.arn
  handler          = each.value.handler
  runtime          = each.value.runtime
  filename         = each.value.zip
  source_code_hash = filebase64sha256(each.value.zip)

  # usa tus variables
  memory_size = var.memory
  timeout     = var.timeout

  environment {
    variables = merge(
      { STAGE = "local" },
      lookup(var.function_env, each.key, {}),         
      { S3_BUCKET_NAME = aws_s3_bucket.videos.id }
    )
  }
  depends_on = [aws_cloudwatch_log_group.lg]
}
