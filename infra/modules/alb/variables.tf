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
