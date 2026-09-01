# Remote state for staging. Same bucket as every stack, distinct key —
# staging and production state never share a file (CLAUDE.md rule).
#
# The state itself survives `terraform destroy`; only resources die. That is
# what makes the next `apply` a clean rebuild rather than an import puzzle.

terraform {
  backend "s3" {
    key          = "envs/staging/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
