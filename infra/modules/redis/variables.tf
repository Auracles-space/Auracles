# Inputs for the ElastiCache Redis module.

variable "environment" {
  description = "Environment name; prefixes resource names."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets (no internet route) for the cache subnet group."
  type        = list(string)
}

variable "security_group_id" {
  description = "SG admitting 6379 from the task SGs only — the only access control this Redis has."
  type        = string
}

variable "node_type" {
  description = "Node size. cache.t4g.micro for the pilot."
  type        = string
  default     = "cache.t4g.micro"
}
