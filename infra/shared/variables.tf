# Inputs for the persistent shared stack.

variable "aws_region" {
  description = "AWS region for all resources. Must match the Neon project's region: the API is server-rendered and issues several queries per page, so a cross-region database is latency paid on every request. London is the closest Neon-supported region to the Nigerian pilot market, whose submarine cables route through Europe regardless."
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
