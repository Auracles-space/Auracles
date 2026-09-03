# Inputs for the persistent shared stack.

variable "aws_region" {
  description = "AWS region for all resources. eu-west-2 (London) has the lowest practical latency from Lagos, the pilot market — West African submarine cables land in and near the UK. Also the ACM certificate here must sit in the ALB's region, so this stack and the environment stacks share one region by construction. Compute, RDS, ElastiCache, and the buckets stay co-located: the worker streams every artifact out of S3 to scan it, and the API queries Postgres per server-rendered page."
  type        = string
  default     = "eu-west-2"
}

variable "root_domain" {
  description = "Registered domain. Stays authoritative at Namecheap and is never managed by Terraform; recorded here only to derive the delegated subdomain."
  type        = string
  default     = "auracles.space"
}

variable "staging_subdomain" {
  description = "Label delegated to Route 53. Only this branch of the DNS tree is handed over; the apex and its mail records stay at Namecheap."
  type        = string
  default     = "staging"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.staging_subdomain))
    error_message = "The subdomain label must be a single DNS label: lowercase letters, digits, and hyphens only."
  }
}

variable "github_repository" {
  description = "GitHub org/repo whose Actions runs may assume the CI role. Part of the OIDC trust condition — a token from any other repository is refused before IAM permissions are even consulted."
  type        = string
  default     = "Auracles-space/Auracles"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Must be the org/repo form, e.g. Auracles-space/Auracles."
  }
}

variable "github_access_token" {
  description = "GitHub personal access token with `repo` scope. Used only when Amplify first connects the repository — Amplify keeps its own installation afterwards, so the token can be revoked once the app exists. Pass it as TF_VAR_github_access_token so it never lands in a tfvars file."
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_publishable_key" {
  description = "Stripe publishable key for the staging frontend. Publishable keys are public by design — this one ships inside the client bundle — so unlike the secret key it is safe in version control."
  type        = string
  default     = ""
}

variable "staging_frontend_custom_domain" {
  description = "Set true to serve the staging frontend at staging.auracles.space. Left false for the first apply because attaching a domain blocks on certificate validation; bring the app up on its amplifyapp.com URL, confirm it builds, then flip this. Same two-pass shape as dns_delegation_complete."
  type        = bool
  default     = false
}

variable "dns_delegation_complete" {
  description = "Set true only after the four NS records from the `namecheap_ns_records` output are live at Namecheap. Gates the ACM validation wait, which cannot succeed before the subtree is actually delegated. Applying this stack is two passes by design; see main.tf."
  type        = bool
  default     = false
}
