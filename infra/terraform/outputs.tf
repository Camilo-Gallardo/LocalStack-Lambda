# Lista de nombres (los detecta de local.lambdas / aws_lambda_function.fn)
output "lambda_names" {
  value = keys(local.lambdas)
}
