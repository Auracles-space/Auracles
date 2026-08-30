# Remote state for the shared stack.
#
# Deliberately partial: the bucket name embeds an AWS account id and so differs
# per account, and a backend block cannot read variables. Supply it at init:
#
#   terraform init -backend-config=backend.hcl
#
# `use_lockfile` is native S3 locking via conditional writes. There is no
# DynamoDB table by design — see infra/README.md.

terraform {
  backend "s3" {
    key          = "shared/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
