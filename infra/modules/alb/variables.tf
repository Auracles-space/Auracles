# Inputs for the ALB module.

variable "environment" {
  description = "Environment name; prefixes resource names."
  type        = string
}

variable "vpc_id" {
  description = "VPC the target group registers in."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets (>= 2 AZs, an ALB requirement)."
  type        = list(string)
}

variable "security_group_id" {
  description = "The alb SG from the networking module."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for the HTTPS listener. Must be in this region — certificates are unusable by load balancers elsewhere."
  type        = string
}

variable "api_container_port" {
  description = "Port the api container listens on."
  type        = number
  default     = 8000
}

variable "account_id" {
  description = "AWS account id, used to keep the access-log bucket name globally unique."
  type        = string
}

variable "access_logs_retention_days" {
  description = "Days to keep ALB access logs before expiry. Logs are a diagnostic, not a record: they answer 'who is hammering us' for a fortnight and then stop paying rent. Raise it only with a reason, because every request writes a line."
  type        = number
  default     = 14
}
