# Inputs for the RDS module.

variable "environment" {
  description = "Environment name; prefixes resource names."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnets (no internet route) for the DB subnet group."
  type        = list(string)
}

variable "security_group_id" {
  description = "SG admitting 5432 from the task SGs only."
  type        = string
}

variable "instance_class" {
  description = "Instance size. db.t4g.micro for the pilot; grow before Multi-AZ, since a bigger single node helps every query and a standby helps only outages."
  type        = string
  default     = "db.t4g.micro"
}

variable "allocated_storage_gb" {
  description = "gp3 storage. 20 GB is the floor and plenty for the pilot; autoscaling below raises the ceiling without a resize event."
  type        = number
  default     = 20
}

variable "multi_az" {
  description = "Standby in a second AZ. Deliberately false for the pilot (decision 2026-09-01): every service runs one task in one AZ, so a surviving database would have nothing to talk to. Flip together with api desired_count >= 2 as launch hardening."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Refuse API-level deletion. True in production; false in staging, whose whole lifecycle is apply-and-destroy."
  type        = bool
}

variable "skip_final_snapshot" {
  description = "Skip the goodbye snapshot on destroy. True only for ephemeral staging — production keeps it, because the final snapshot is the last line against a mistaken destroy."
  type        = bool
}

variable "backup_retention_days" {
  description = "PITR window. 7 covers the pilot; 0 disables backups entirely and is only acceptable for staging."
  type        = number
  default     = 7
}

variable "database_name" {
  description = "Initial database created in the instance."
  type        = string
  default     = "auracles"
}

variable "master_username" {
  description = "Master role name. Not 'postgres' so a credential-stuffing guess needs both halves."
  type        = string
  default     = "auracles"
}
