terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    datadog = {
      source = "DataDog/datadog"
    }
    onepassword = {
      source  = "1Password/onepassword"
      version = "~> 2.0"
    }
  }

  backend "s3" {
  }
}

provider "aws" {
  region = var.aws_region
}

# Uses 1Password CLI integration
provider "onepassword" {
  account = "transluce.1password.com"
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}
