# Terraform and provider version constraints for the persistent shared stack.
#
# Terraform >= 1.11 is a hard floor, not a preference: native S3 state locking
# (`use_lockfile`) only reached GA there. On 1.10 it is experimental, and below
# that the S3 backend cannot lock without a DynamoDB table, which this project
# deliberately does not create.

terraform {
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Bounded below where the resources used here are stable, and below the
      # next major so a provider release cannot silently change behaviour on an
      # unattended `init`.
      version = ">= 5.70.0, < 7.0.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Credentials come from the default chain (env vars or ~/.aws/credentials),
  # never from this file. No profile is pinned so the same code works from a
  # laptop and from CI's OIDC role without editing.

  default_tags {
    tags = {
      Project   = "auracles"
      ManagedBy = "terraform"
      Stack     = "shared"
      # Marks resources that must survive `terraform destroy` of any
      # environment stack. Deleting the hosted zone would reassign its
      # nameservers and break the Namecheap delegation.
      Lifecycle = "persistent"
    }
  }
}
