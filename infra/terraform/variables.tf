variable "region" {
  type    = string
  default = "us-east-1"
}

# mapa opcional: por función -> mapa de env vars
variable "function_env" {
  type = map(map(string))
  default = {}
}

variable "memory" {
  type    = number
  default = 2048
}

variable "timeout" {
  type    = number
  default = 900
}
