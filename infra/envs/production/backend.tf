# Remote state for production. Same bucket as every stack, distinct key —
# staging and production state never share a file (CLAUDE.md rule), so a
# mistake in one environment cannot corrupt the other's record of reality.

terraform {
  backend "s3" {
    key          = "envs/production/terraform.tfstate"
    region       = "eu-west-2"
    encrypt      = true
    use_lockfile = true
  }
}
