# Busca todos los dist.zip: lambdas/<nombre>/dist.zip
locals {
  lambda_zip_paths = fileset("${path.module}/../../lambdas", "*/dist.zip")

  lambdas = {
    for rel in local.lambda_zip_paths :
    split("/", rel)[0] => {
      zip     = "${path.module}/../../lambdas/${rel}"
      handler = "handler.handler"
      runtime = "python3.11"
      env     = { STAGE = "local" }
    }
  }
}

# Log groups por función
resource "aws_cloudwatch_log_group" "lg" {
  for_each          = local.lambdas
  name              = "/aws/lambda/${each.key}"
  retention_in_days = 7
}

# Reutiliza tu rol ya creado en iam.tf:
# resource "aws_iam_role" "lambda_exec" { ... }
# resource "aws_iam_role_policy_attachment" "basic_exec" { ... }

# Funciones Lambda
resource "aws_lambda_function" "fn" {
  for_each         = local.lambdas
  function_name    = each.key
  role             = aws_iam_role.lambda_exec.arn
  handler          = each.value.handler
  runtime          = each.value.runtime
  filename         = each.value.zip
  source_code_hash = filebase64sha256(each.value.zip)

  environment { variables = each.value.env }

  depends_on = [aws_cloudwatch_log_group.lg]
}

