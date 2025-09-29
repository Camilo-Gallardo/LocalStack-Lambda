terraform {
	required_providers {
	  aws = {
	    source = "hashicorp/aws"
	    version = "~> 5.0"
	}
    }
}


provider "aws" {
  access_key = "test"
  secret_key = "test"
  region     = var.region

  # Ajustes para LocalStack (AWS provider v5)
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true

  endpoints {
    apigateway     = "http://localhost:4566"
    cloudwatch     = "http://localhost:4566"
    cloudwatchlogs = "http://localhost:4566"
    iam            = "http://localhost:4566"
    lambda         = "http://localhost:4566"
    s3             = "http://localhost:4566"
    sts            = "http://localhost:4566"
    events         = "http://localhost:4566"
  }
}
