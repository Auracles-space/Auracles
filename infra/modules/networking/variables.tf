# Inputs for the networking module.

variable "environment" {
  description = "Environment name (staging, production). Prefixes every resource name so both environments can coexist in one account without collision."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "vpc_cidr" {
  description = "VPC CIDR. Staging and production use disjoint ranges so the two VPCs could be peered later without renumbering."
  type        = string
}

variable "az_count" {
  description = "How many availability zones to spread subnets across. Two even at desired_count=1: subnet groups for RDS and ElastiCache require subnets in at least two AZs, and the ALB requires two — this is an AWS floor, not an HA posture."
  type        = number
  default     = 2
}

variable "api_container_port" {
  description = "Port the api container listens on; the ALB's only permitted path into the tasks."
  type        = number
  default     = 8000
}
