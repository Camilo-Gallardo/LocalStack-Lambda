resource "aws_cloudwatch_log_group" "hello" {
  name = "/aws/lambda/hello_world"
  retention_in_days = 7
}


resource "aws_lambda_function" "hello_world" {
  function_name = "hello_world"
  role = aws_iam_role.lambda_exec.arn
  handler = "handler.handler"
  runtime = "python3.11"
  filename = "${path.module}/../../lambdas/hello_world/dist.zip"
  source_code_hash = filebase64sha256("${path.module}/../../lambdas/hello_world/dist.zip")


  environment {
    variables = {
      STAGE = "local"
    }
  }
  depends_on = [aws_cloudwatch_log_group.hello]
}
