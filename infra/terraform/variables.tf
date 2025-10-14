variable "region" {
  type    = string
  default = "us-east-1"
}

# mapa opcional: por función -> mapa de env vars
variable "function_env" {
  type = map(map(string))
  default = {} # sin override, usa solo STAGE=local
}

variable "memory" {
  type    = number
  default = 128
}

variable "timeout" {
  type    = number
  default = 90000
}
