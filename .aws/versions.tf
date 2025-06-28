terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"   # or the latest 5.x you have available
    }
  }
}

provider "aws" {
  region = var.aws_region
}
