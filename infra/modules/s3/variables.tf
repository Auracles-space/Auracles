# Inputs for the application buckets module.

variable "environment" {
  description = "Environment name; part of every bucket name."
  type        = string
}

variable "account_id" {
  description = "AWS account id, suffixing bucket names. S3 names are global across all AWS customers, so unsuffixed names are squattable and collide across accounts — the June-era consoles buckets (auracles-artifacts-prod etc.) were only safe by luck."
  type        = string
}

variable "force_destroy" {
  description = "Allow destroy to delete non-empty buckets. True for ephemeral staging, whose artifacts are QA leftovers by definition. False in production: a destroy that would lose user artifacts must fail instead."
  type        = bool
}

variable "cors_allowed_origins" {
  description = "Origins allowed for browser-direct presigned uploads/downloads (artifacts and avatars). The frontend origin(s) for the environment."
  type        = list(string)
}
