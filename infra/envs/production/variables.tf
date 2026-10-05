# Inputs for the production stack.

variable "aws_region" {
  description = "Must match infra/shared's region: the ACM certificate production attaches to its ALB only works for load balancers in the certificate's own region."
  type        = string
  default     = "eu-west-2"
}

variable "vpc_cidr" {
  description = "Production VPC range. Disjoint from staging's (10.0.0.0/16) so the two could be peered without renumbering."
  type        = string
  default     = "10.1.0.0/16"
}

variable "state_bucket" {
  description = "State bucket name, for reading the shared stack's outputs. Same value as backend.hcl's bucket, duplicated because backend blocks cannot read variables but terraform_remote_state data sources can. Committed in production.tfvars — the name embeds the account id but is not a secret."
  type        = string
}
