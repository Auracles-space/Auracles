# Staging environment. Grows slice by slice in the cutover order:
# networking (this slice) → RDS + ElastiCache → ECS + ALB → DNS records.
#
# Reads the shared stack's outputs (zone, certificate, ECR) through
# terraform_remote_state rather than data lookups by name, so the wiring
# breaks loudly at plan time if shared/ has not been applied yet.

data "terraform_remote_state" "shared" {
  backend = "s3"

  config = {
    bucket = var.state_bucket
    key    = "shared/terraform.tfstate"
    region = var.aws_region
  }
}

module "networking" {
  source = "../../modules/networking"

  environment = "staging"
  vpc_cidr    = var.vpc_cidr
}
