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

variable "dns_delegation_complete" {
  description = "Set true only after the four NS records from the `namecheap_ns_records` output are live at Namecheap. Gates the ACM validation wait, which cannot succeed before the subtree is actually delegated. Applying this stack is two passes by design; see main.tf."
  type        = bool
  default     = false
}
