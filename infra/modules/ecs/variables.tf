# Inputs for the ECS module: cluster, IAM, log groups, task definitions, and
# the three services (api, worker, beat).

variable "environment" {
  description = "Environment name; prefixes resource names."
  type        = string
}

variable "aws_region" {
  description = "Region, for awslogs configuration."
  type        = string
}

variable "backend_image" {
  description = "Full image reference (repository URL + tag/digest) all three services run. One image, three commands — the deploy promotes a single artifact."
  type        = string
}

variable "public_subnet_ids" {
  description = "Where tasks launch (public IPs are their only outbound path — no NAT)."
  type        = list(string)
}

variable "api_security_group_id" {
  type        = string
  description = "SG for api tasks."
}

variable "worker_security_group_id" {
  type        = string
  description = "SG for worker tasks."
}

variable "beat_security_group_id" {
  type        = string
  description = "SG for beat tasks."
}

variable "target_group_arn" {
  description = "ALB target group the api service registers into."
  type        = string
}

variable "api_container_port" {
  description = "Port the api container listens on."
  type        = number
  default     = 8000
}

variable "environment_variables" {
  description = "Plain (non-secret) env vars shared by all three services. Per-service pool sizing is layered on top inside the module."
  type        = map(string)
}

variable "secret_arns" {
  description = "Secret env vars as name => Secrets Manager ARN. Injected by ECS at task start; values never appear in task definitions or state."
  type        = map(string)
}

variable "use_spot" {
  description = "Run worker and beat on Fargate Spot (~70% off). The api always stays on-demand — it serves users; a reclaimed api task is a user-facing error, a reclaimed worker task is a re-queued Celery job."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch retention. The default of forever is a silent cost creeper; 30 days covers any realistic incident lookback at pilot scale."
  type        = number
  default     = 30
}

variable "s3_bucket_names" {
  description = "The four application bucket names, for the task role's S3 grant."
  type        = list(string)
}

variable "clamav_image" {
  description = "ClamAV sidecar image for the worker task."
  type        = string
  default     = "clamav/clamav:1.4"
}
