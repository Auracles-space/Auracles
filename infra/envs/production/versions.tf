# Terraform and provider pins for the production stack.
#
# Production is PERMANENT. The opposite of staging in every respect that
# matters here: nothing in this stack may be destroyed casually, the database
# refuses API-level deletion, the buckets refuse to be emptied, and the ALB
# carries deletion protection. A plan that wants to destroy anything here is a
# human decision, never an apply.

terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70.0, < 7.0.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0, < 4.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "auracles"
      ManagedBy   = "terraform"
      Stack       = "production"
      Environment = "production"
      # The opposite marker to staging's "ephemeral": nothing here is expected
      # to die, and a destroy plan touching this tag wants explaining.
      Lifecycle = "permanent"
    }
  }
}
