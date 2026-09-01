# Terraform and provider pins for the staging stack.
#
# Staging is EPHEMERAL: applied for a QA cycle, destroyed after. Nothing in
# this stack may be un-destroyable — anything that must persist (DNS zone,
# certificate, ECR) lives in infra/shared instead.

terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 7.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "auracles"
      ManagedBy   = "terraform"
      Stack       = "staging"
      Environment = "staging"
      # The opposite marker to shared/: everything here is expected to die on
      # `terraform destroy` at the end of a QA cycle.
      Lifecycle = "ephemeral"
    }
  }
}
